# Spec: EKS Subnet Planner scenario model (`subnet_planner.py` + `POST /api/plan`)

Task: t_2c5fc727 · Assignee: architect · Repo: /home/mariusz/eks-subnet-calculator (main)

## 1. Problem & acceptance
Given ONLY a VPC CIDR, enumerate all feasible cluster scenarios
(AZs × networking × pods-per-node → max nodes) that fit that CIDR, reusing
the existing footprint model verbatim. Deliverable: this spec; no implementation.
Gaps are raised as question comments, never silently filled.

## 2. Endpoint contract (app.py)
```
POST /api/plan  body {"vpc_cidr": "10.0.0.0/16"}
  invalid  -> 400 {"error": str}      # validators.is_valid_vpc_cidr
  valid    -> 200 {"vpc_cidr": str, "vpc_total_ips": int,
                   "scenario_count": int, "scenarios": [...]}
```
Route mirrors /api/calculate structure: `validators.is_valid_vpc_cidr(cidr)`
first (`None`/missing key -> its own "CIDR is required" error -> 400), then
`subnet_planner.plan_scenarios(cidr)`; `except ValueError -> 400 {"error": str(e)}`,
`except Exception -> 500 {"error": "Internal server error"}`.
`vpc_cidr` in response is the normalized form (`str(ipaddress.IPv4Network(cidr))`).
Existing endpoints unchanged.

## 3. plan_scenarios() pseudo-code (exact)
```
LADDER = [1,2,4,8,16,32,64,128,256,512,1024,2048,4096,8192,10000]
AZS    = [1..6]; NET = ["auto","custom"]; PPN = [25,50,110,250]

footprint(n, ppn, az, net):                 # == suggest_minimum_vpc_cidr total
    custom  = (net == "custom")
    sp      = calculate_subnet_size(n, ppn, az, use_custom_pod_cidr=custom)
    S       = 2 ** (32 - sp)               # per node-subnet IPs
    total   = az * (2*S + 16)             # public+private per AZ, /28 cp per AZ
    total  += 2 * 4096                    # service /20 + one /20 alignment headroom
    if not custom:
        pp      = calculate_pod_cidr_size(n, ppn)
        total  += 2 * 2 ** (32 - pp)     # auto pod CIDR + alignment headroom
    return total                          # custom pods external: 0 contribution

plan_scenarios(vpc_cidr):
    ok, err = validators.is_valid_vpc_cidr(vpc_cidr); if not ok: raise ValueError(err)
    vpc_total = IPv4Network(vpc_cidr).num_addresses
    scenarios = []
    for az in AZS, net in NET, ppn in PPN:
        best = None
        for n in LADDER ascending:        # footprint monotonic non-decreasing in n
            if footprint(n, ppn, az, net) <= vpc_total: best = n
            else: break
        if best is None: continue         # even 1 node doesn't fit -> drop combo
        total = footprint(best, ppn, az, net)
        invpc = 3*az + (2 if net=="auto" else 1)   # in-VPC subnets; custom pod is external
        scenarios.append({
            "scenario_id": f"az{az}-{net}-{ppn}",
            "az_count": az, "networking": net, "pods_per_node": ppn,
            "max_nodes": best, "total_subnets": 3*az + 2,
            "total_ips": total,
            "available_ips": total - 3*invpc,
            "vpc_utilization_percent": round(total/vpc_total*100, 1),
            "fits": True })
    scenarios.sort(key=(-util, az, -max_nodes))     # tie-breaks per stamped DECISIONS
    return {"vpc_cidr": normalized, "vpc_total_ips": vpc_total,
            "scenario_count": len(scenarios), "scenarios": scenarios[:48]}
```
Invariants: `footprint` is monotonic non-decreasing in n (both size helpers scan
prefixes monotonically), so "last ladder value that fits" = early-break scan.
`total_subnets` is always `3*az+2` (service + pod entries listed even when the
pod block is external); `available_ips` charges 3 reserved IPs only to subnets
that occupy VPC space (`invpc = 3*az+2` auto, `3*az+1` custom — service stays
in-VPC in both modes, mirroring calculate_subnets accounting).

## 4. Worked example: 10.0.0.0/16 (vpc_total = 65,536)
Verified by running the existing calculator functions on this repo.

| scenario_id    | az | net    | ppn | max_nodes | subnet | pod | total_ips | available_ips | util % |
|----------------|----|--------|-----|-----------|--------|-----|-----------|---------------|--------|
| az3-auto-110   | 3  | auto   | 110 | 64        | /20    | /19 | 49,200    | 49,167        | 75.1   |
| az1-auto-250   | 1  | auto   | 250 | 32        | /18    | /19 | 57,360    | 57,345        | 87.5   |
| az3-custom-250 | 3  | custom | 250 | 10,000    | /20    | ext | 32,816    | 32,786        | 50.1   |

Row 1 arithmetic (az=3, auto, ppn=110, n=64):
subnet: 64·110/3 + 64·16/3 + 128 = 2,816 -> /20 (4,096).
3·(2·4,096 + 16) = 24,624; service 2·4,096 = 8,192 -> 32,816;
pods 64·110 = 7,040 -> /19 (8,192), ×2 = 16,384 -> total 49,200.
Boundary: n=128 -> /19 subnets + /18 pod -> 90,160 > 65,536 (rejects).
util 49,200/65,536 = 75.1%; avail 49,200 − 3·11 = 49,167.

Row 2 (az=1, auto, ppn=250, n=32): 32·250 + 32·16 + 128 = 8,640 -> /18;
2·16,384+16 = 32,784; +8,192 = 40,976; pods 8,000 -> /19 ×2 = 16,384
-> 57,360. n=64 -> 106,512 > 65,536 (rejects). util 87.5%; avail 57,360−3·5.

Row 3 (az=3, custom, ppn=250, n=10,000): 10,000/3 + 128 = 3,461 -> /20;
3·(2·4,096+16) = 24,624; +8,192 = 32,816; pods external (0). Ladder plateau:
n/3+128 ≤ 4,096 up to n=11,904, so ladder top 10,000 fits -> max_nodes=10,000.
avail 32,816 − 3·10 (in-VPC = 9 node/cp + service) = 32,786. util 50.1%.

## 5. Numerical consistency with suggest_minimum_vpc_cidr
footprint() is arithmetically identical to suggest_minimum_vpc_cidr()'s total,
so the fit predicate must agree: combo(n, ppn, az, net) fits VPC prefix P
⇔ P ≤ suggested-prefix(n, ppn, az, net). Verified samples:

| n | ppn | az | net    | footprint | suggested | check |
|---|-----|----|--------|-----------|-----------|-------|
|100| 110 | 2  | auto   | 73,760    | /15 (131,072) | fits; /16=65,536 fails -> tight ✓ |
|250| 250 | 1  | custom | 9,232     | /18 (16,384)  | fits; /19=8,192 fails -> tight ✓ |
| 64|  50 | 3  | auto   | 28,720    | /17 (32,768)  | fits; /18=16,384 fails -> tight ✓ |

## 6. Edge-case rules
- Invalid CIDR (malformed, octet >255, non-canonical, /29+ prefix): endpoint 400
  from is_valid_vpc_cidr; plan_scenarios raises ValueError with same message.
- Valid but too small: minimum viable footprint = 9,232 IPs (az=1, auto, n=1,
  ppn=25; custom variant 8,720) -> any VPC with prefix ≥ /19 (≤8,192 IPs,
  incl. /25 and /28) returns valid 200 with scenario_count 0 and scenarios [].
  Small VPCs are NOT errors.
- Ladder top 10,000 == is_valid_node_count ceiling; plateau behavior (§4 row 3)
  means ladder values above the top are not invented.
- Cap 48: enumeration space is 6×2×4 = 48 combos, so sorting/cap never trims;
  it is defensive only. /16 yields exactly 48 scenarios.
- No overlap/allocator validation here (calculator's job); planner is arithmetic
  feasibility only.

## 7. File map
- subnet_planner.py (NEW, repo root): LADDER/AZS/NET/PPN constants, footprint(),
  plan_scenarios(). Imports only ipaddress + project modules; no new deps.
- app.py (MODIFY): add `POST /api/plan` route (§2); existing routes untouched.
- planner.html (NEW): minimal page — CIDR input, POST /api/plan, sortable
  scenario table (same CSS tokens as index.html).
- index.html (MODIFY): nav link to /planner only.
- test_subnet_planner.py (NEW): unit — exact §4 rows; monotonic boundary checks
  (n and 2n at max_nodes); §5 consistency loop; /25 and /28 -> count 0;
  invalid CIDR -> ValueError; sort order + [:48] cap.
- test_app_plan.py (NEW): integration — 200 response schema keys; /29 -> 400
  {"error"}; missing body key -> 400. Existing test files unchanged.

## 8. Decisions, clarification, residual risk
All stamped DECISIONS adopted verbatim. One clarification (not a deviation):
"available_ips = consumed footprint minus 3 reserved IPs per in-VPC subnet" —
custom mode's external pod block is not in-VPC, so reserved count is
3×(3·az+1), not 3×total_subnets; auto mode uses 3×(3·az+2). scenario_id format
f"az{az}-{net}-{ppn}" chosen (unstamped, deterministic, unique per combo).
Residual risks: (1) footprint is the conservative 2×-headroom model, so reported
utilization may exceed what calculate_subnets' exact layout would show — accepted
by DECISION (consistency with suggest_minimum_vpc_cidr); (2) custom-mode
max_nodes=10,000 plateau can surprise UI consumers — surface the plateau note
in planner.html copy.
