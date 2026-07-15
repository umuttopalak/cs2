# DMA and Kernel-to-User Telemetry: Physical Memory Mapping Overhead in Real-Time 3D Environments

## 1. Motivation

Real-time 3D applications (game engines, robotics simulators, physics visualizers) maintain
large arrays of dynamically updated spatial structures — object transforms, bounding volumes,
scene-graph nodes. A recurring systems question is: **what is the actual overhead of virtual
address translation when repeatedly sampling these structures at high frequency**, and does
bypassing it via physical-memory access (as a PCIe DMA device would) meaningfully change the
cost model?

To reason about this without tying the discussion to any specific shipped binary or proprietary
struct layout, we use a synthetic stand-in for "a dynamically updated spatial entity":

```cpp
// Synthetic example — not tied to any specific application's real memory layout.
struct Vec3 { float x, y, z; };

struct SimEntity {
    uint32_t entityId;      // 0x00
    Vec3     position;      // 0x04
    Vec3     velocity;      // 0x10
    uint16_t teamMask;      // 0x1C
    float    healthNorm;    // 0x1E  (0.0 - 1.0)
    uint32_t flags;         // 0x22
};                          // sizeof == 0x28 (packed, illustrative)

struct SimWorldState {
    uint32_t   entityCount;
    SimEntity* entityArray;  // pointer to contiguous SimEntity[] in process VA space
};
```

This is deliberately generic. The translation math below applies identically whether
`entityArray` points at game objects, robotics actors, or particle simulation nodes — the
memory subsystem doesn't know or care what the bytes mean.

## 2. Virtual-to-Physical Translation Cost

On x86-64 with 4-level paging (or 5-level with LA57), a virtual address is resolved through:

```
VA -> PML4 -> PDPT -> PD -> PT -> Physical Page + offset
```

Each level is a memory access (usually cached in the TLB after the first walk). The **steady-state**
cost for a userspace read of `SimWorldState::entityArray[i]` is:

1. TLB lookup (near-free, ~1 cycle, if resident)
2. On TLB miss: hardware page walker performs up to 4 sequential memory reads (worst case
   ~150-200 cycles combined, mitigated by walk caches in modern CPUs)
3. Copy from cache line to register

The overhead conversation is really about **TLB miss rate**, not the existence of virtual memory
itself. A tight polling loop over a small, hot entity array will have this fully amortized after
the first few iterations, since the pages stay resident in the TLB.

## 3. What Changes With Physical-Address (DMA-style) Access

A theoretical PCIe DMA device (or any bus-mastering peripheral) does not have a TLB or CR3 context
of its own for user-mode virtual addresses — it operates on physical addresses (or an IOMMU-mapped
address space, if VT-d/AMD-Vi is enabled). To reach `SimWorldState`, kernel-side pseudocode would
need to resolve the *current* virtual-to-physical mapping once, then hand the physical address to
the device:

```cpp
// Kernel-mode pseudocode illustrating the *concept* of VA -> PA resolution.
// This is generic Windows kernel API surface, not tied to any specific target.
PHYSICAL_ADDRESS ResolveEntityArrayPhysical(PVOID userVirtualAddress) {
    // MmGetPhysicalAddress walks the current process's page tables
    // (equivalent conceptually to a manual PML4->PDPT->PD->PT walk)
    // and returns the backing physical page + offset.
    return MmGetPhysicalAddress(userVirtualAddress);
}
```

Two things fall out of this that are worth stating precisely, because they're often glossed over
in informal discussions of "DMA bypasses the OS":

- **The page table walk still happens.** `MmGetPhysicalAddress` is not free — it performs
  (or reuses a cached result of) the exact same PML4→PT walk described in §2. DMA doesn't
  eliminate address translation; it eliminates translation *on every subsequent access*,
  because the physical address is captured once and reused, whereas the page could be
  paged out, moved, or remapped later.
- **Physical addresses are not stable.** Non-locked user pages can be paged to disk or
  relocated by the memory manager at any time. A physical address cached from one
  `MmGetPhysicalAddress` call is only guaranteed valid until the next page-fault-eligible
  event unless the page is pinned (`MmProbeAndLockPages` / non-paged pool allocation).
  This is the real engineering cost that "raw physical read" designs pay: they must either
  re-resolve VA→PA on a schedule, or lock pages down (with the scheduling/memory-pressure
  costs that entails), trading one overhead for another rather than eliminating it.

## 4. Net Overhead Comparison

| Access path                          | Per-read cost driver                          | Stability guarantee |
|---------------------------------------|-----------------------------------------------|----------------------|
| Direct VA read (steady-state, hot TLB)| ~1 cycle (TLB hit)                             | Automatic (OS-managed) |
| Direct VA read (cold TLB)              | ~150-200 cycles (hardware page walk)           | Automatic (OS-managed) |
| PA resolved once, reused for N reads   | Amortized: one walk / N reads                  | Only valid until page moves/pages out |
| PA reused without re-validation         | Cheapest per-read, but **incorrect** after any page reclaim/move | None — silent data corruption risk |

The practical conclusion for the whitepaper: bypassing virtual memory via physical addressing
doesn't remove translation cost from the system, it just relocates *when* that cost is paid and
shifts the correctness burden from the OS (automatic, always-consistent) onto whoever is holding
the cached physical address (manual, time-bounded, and unsafe across page reclaim events).

## 5. IOMMU / VT-d Remapping

Sections 2-4 assumed a device operating on raw physical addresses, which is the degenerate case
(IOMMU disabled, or the device driver granted an identity-mapped DMA window). On any modern
platform with Intel VT-d or AMD-Vi enabled, that assumption doesn't hold — the device does not
see physical memory directly at all. It sees a **device address space (DVA / IOVA)** that the
IOMMU translates to physical addresses via its own dedicated page tables, functionally a second,
parallel MMU sitting between the PCIe fabric and DRAM.

```
Device-issued address (IOVA) -> IOMMU page tables -> Physical Page + offset
                                        ^
                          managed by IOMMU driver / VFIO / DMA-remapping unit,
                          entirely independent of the CPU's CR3 / process page tables
```

This changes the cost *and* the threat model in ways worth separating out:

- **A second translation layer, not a bypass of the first.** The CPU-side VA→PA walk described
  in §2 is unrelated to and unaffected by IOMMU remapping — that walk still happens whenever the
  *CPU* touches `SimWorldState::entityArray`. IOMMU remapping only governs what a *device*
  (the DMA-capable PCIe endpoint) is allowed to address. A design that assumed "IOMMU on removes
  page-walk overhead" is conflating two independent translation paths.
- **IOMMU translation has its own miss cost.** Just like a CPU TLB, the IOMMU maintains an IOTLB.
  A cold IOVA lookup costs a walk through the IOMMU's own multi-level page tables (structurally
  analogous to PML4→PT, held in a reserved region of memory the OS's DMA-remapping driver
  manages), so the "steady-state vs. cold-walk" table in §4 has a direct IOMMU-side analogue —
  IOTLB hit vs. IOTLB miss.
- **The consistency problem from §3 gets fixed here, not worked around.** Under IOMMU remapping,
  the OS (via `IoMapTransfer` / VFIO `DMA_MAP` equivalents) registers the exact page range a
  device is permitted to target and can pin it for the transfer's lifetime; the device's IOVA
  stays valid because the OS is contractually obligated to update the IOMMU tables (or refuse to
  reclaim the underlying page) for as long as the mapping is active. This is the structural fix
  for the "physical address goes stale mid-transfer" failure mode identified in §3 — instead of
  the DMA design silently racing the page reclaimer, the mapping's validity window is now
  explicit and OS-enforced.
- **Isolation as the actual design payoff.** Because a device's DMA is constrained to only the
  IOVA ranges the OS has mapped for it, a misbehaving or compromised device cannot address
  arbitrary physical memory — the IOMMU enforces the same containment for peripherals that page
  tables enforce between processes. This is the property VT-d/AMD-Vi exists for (Kernel DMA
  Protection on Windows, `iommu=pt`/`intel_iommu=on` on Linux); the performance discussion in
  §2-4 is a secondary effect of enabling it, not the primary motivation.

Net effect for the cost model: enabling IOMMU remapping does not remove the translation overhead
identified in §2 — it adds a second, independent translation stage with its own cache (IOTLB) and
its own miss penalty, in exchange for closing the correctness/isolation gap that raw physical
addressing in §3 left open.

## 6. TLB Shootdown: the Dual of "Physical Address Goes Stale"

Section 3 framed staleness from the reader's side: a cached physical address can outlive the
mapping it was taken from. The same event looks different from the writer's side — whenever the
memory manager unmaps, moves, or changes protection on a page (reclaiming it, migrating it for
NUMA locality, or servicing a `VirtualFree`), every CPU core that might have cached the old
translation in its TLB needs to be told to drop it. On multi-core x86-64 this is done with an
**IPI-based shootdown**:

```
Core 0 (initiator): modifies PTE, then must ensure no core still translates via the old PTE
  1. Core 0 sends an Inter-Processor Interrupt (IPI) to every core whose TLB might hold the entry
  2. Each target core executes INVLPG (or a broader flush) in its IPI handler
  3. Core 0 blocks until all targets acknowledge (a synchronization barrier)
```

This is the direct cost side-effect of the same event that makes cached physical addresses unsafe
in §3 — the OS isn't just invalidating one core's TLB, it's paying a synchronous, all-core
interrupt round-trip so that *no* core can continue reading through a translation that no longer
matches the PTE. The more cores in the shootdown set, and the more frequently pages are
remapped/reclaimed, the more this dominates — which is precisely why pinning a page (§7) is
preferable to a design that keeps re-resolving `MmGetPhysicalAddress` on a timer: pinning removes
the page from the reclaim/remap path entirely, so it can never trigger a shootdown in the first
place, whereas polling VA→PA just narrows the staleness *window* without addressing the
underlying race.

## 7. Non-Paged Pool vs. Locked User Pages

Section 3 named two legitimate mechanisms for keeping a physical mapping valid over time without
racing the memory manager. They solve the same problem — "this physical address must not move or
disappear while I hold it" — but at different layers and with different cost profiles.

**Non-paged pool** (`ExAllocatePool2` with `POOL_FLAG_NON_PAGED`, or the legacy
`NonPagedPool` tag) is kernel-owned memory that is guaranteed resident for its entire lifetime —
it is never eligible for the page reclaimer or the swapper, by construction. It is the natural
choice when the *kernel itself* allocates the buffer a device will DMA into or out of (a ring
buffer, a completion queue): there is no "locking" step because the memory was never pageable.
The cost is paid up front and structurally, not per-transfer — non-paged pool is a scarcer,
more tightly accounted resource than ordinary paged memory, so over-allocating it has systemic
effects (historically a real denial-of-service vector on Windows before pool quotas tightened).

**Locked user pages** (`MmProbeAndLockPages` around an `MDL`, or `mlock`/`mmap(MAP_LOCKED)` on
Linux) address the opposite scenario: the buffer is ordinary pageable user memory (e.g. a
userspace buffer supplied to `WriteFile`/`DeviceIoControl` for a DMA transfer), and it needs a
*temporary* residency guarantee for the duration of one operation, not for its whole lifetime.
Locking probes the pages into memory if they aren't already resident, then marks them ineligible
for reclaim/relocation until explicitly unlocked — at which point they return to being ordinary,
reclaimable user memory. This is cheaper in aggregate (you're not permanently taxing a scarce
pool) but requires the driver to correctly bound the lock's lifetime to the transfer; holding a
lock indefinitely on user memory is functionally equivalent to a non-paged allocation, minus the
pool accounting, and is a common source of driver memory-pressure bugs.

The dividing line, restated: non-paged pool answers "the kernel needs a buffer that is *never*
pageable"; locked user pages answer "userspace's buffer needs to be pageable *usually*, but
briefly can't be." Both exist because the alternative — reading a raw physical address captured
once and trusting it stays valid (§3) — has no correctness guarantee at all once the page
reclaimer or NUMA balancer runs.

## 8. IOTLB Invalidation Under Frequent Remapping

Section 5 introduced the IOTLB as the IOMMU's own translation cache, structurally analogous to
the CPU's TLB. It inherits the CPU side's invalidation problem in a stricter form: whenever the
IOMMU driver tears down or repoints an IOVA→PA mapping (a `DMA_UNMAP` on Linux/VFIO, or the
Windows DMA-remapping equivalent), any device that cached the old translation in its IOTLB entry
must be prevented from using it before the underlying physical page is reused for something else.

```
IOMMU driver unmaps IOVA range:
  1. Update IOMMU page tables (remove/repoint the PTE-equivalent entry)
  2. Issue IOTLB invalidation (Intel: Queued Invalidation / IOTLB Invalidate Descriptor;
     AMD-Vi: INVALIDATE_IOMMU_PAGES command)
  3. Wait for invalidation completion status before the page is considered safe to reuse
     (analogous to the shootdown barrier in §6, but the "core" being waited on is the IOMMU
     hardware unit itself, and transitively, any in-flight device transaction)
```

The practical consequence for a design that remaps IOVA ranges frequently (as opposed to mapping
once at initialization and reusing the same range for the buffer's lifetime) is that every remap
pays this invalidate-and-wait cost, which is a bus-level operation, not a same-core instruction
like `INVLPG` — meaningfully more expensive per event than a CPU TLB shootdown, and the reason
production DMA drivers strongly favor a **map-once, reuse-the-range** pattern (matching the
non-paged pool / locked-page discipline from §7) over dynamically remapping per-transfer.

## 9. Summary

Across §2-8, the same shape recurs at three layers — CPU paging, IOMMU remapping, and the
invalidation protocols that keep each layer's cache coherent with the page tables underneath it:
translation cost is never eliminated, only relocated, cached, or amortized, and every mechanism
that speeds up the common case (TLB, IOTLB, cached physical addresses) requires a corresponding
invalidation mechanism (shootdown, IOTLB invalidate, pinning) to remain correct when the
underlying mapping changes. A whitepaper modeling "DMA overhead vs. virtual memory overhead"
should treat these as one cost accounting problem with three interacting layers, not as a binary
choice between "slow virtual memory" and "fast raw physical access."
