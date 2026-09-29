#!/usr/bin/env python3
"""EKS Subnet Planner - scenario enumeration for a given VPC CIDR.

Given only a VPC CIDR, enumerate all feasible cluster scenarios
(AZs x networking x pods-per-node -> max nodes) that fit that CIDR,
reusing the existing footprint model from subnet_calculator verbatim.
Spec: docs/specs/eks-subnet-planner-scenario-model.md (task t_2c5fc727).
"""

import ipaddress
from typing import Any, Dict

import subnet_calculator
import validators

# Scenario enumeration space (6 AZs x 2 networking modes x 4 pods-per-node = 48 combos)
AZ_COUNTS = list(range(1, 7))
NETWORKING_MODES = ["auto", "custom"]
PODS_PER_NODE_OPTIONS = [25, 50, 110, 250]
# Node ladder; top value 10000 == validators.is_valid_node_count ceiling
NODE_LADDER = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 10000]

SERVICE_CIDR_PREFIX = 20
MAX_SCENARIOS = 48


def footprint(node_count: int, pods_per_node: int, az_count: int, networking: str) -> int:
    """Total VPC IPs consumed by a cluster config (== suggest_minimum_vpc_cidr total).

    Public + private node subnets + /28 control plane per AZ, service /20 plus one
    /20 of alignment headroom, and — for auto networking — the pod CIDR block plus
    one block of alignment headroom. Custom networking pods live outside the VPC
    (CG-NAT) and consume no VPC space.
    """
    use_custom_pod_cidr = networking == "custom"
    subnet_prefix = subnet_calculator.calculate_subnet_size(
        node_count, pods_per_node, az_count, use_custom_pod_cidr=use_custom_pod_cidr
    )
    subnet_ips = 2 ** (32 - subnet_prefix)
    control_plane_ips = 2 ** (32 - subnet_calculator.calculate_control_plane_size())

    total = az_count * (2 * subnet_ips + control_plane_ips)
    total += 2 * (2 ** (32 - SERVICE_CIDR_PREFIX))
    if not use_custom_pod_cidr:
        pod_prefix = subnet_calculator.calculate_pod_cidr_size(node_count, pods_per_node)
        total += 2 * (2 ** (32 - pod_prefix))
    return total


def plan_scenarios(vpc_cidr: str) -> Dict[str, Any]:
    """Enumerate all feasible cluster scenarios that fit the given VPC CIDR.

    Raises ValueError for invalid CIDRs (same messages as validators.is_valid_vpc_cidr).
    Valid-but-too-small VPCs return scenario_count 0 with an empty scenarios list.
    """
    is_valid, error = validators.is_valid_vpc_cidr(vpc_cidr)
    if not is_valid:
        raise ValueError(error)

    vpc_network = ipaddress.IPv4Network(vpc_cidr)
    vpc_total_ips = vpc_network.num_addresses

    scenarios = []
    for az_count in AZ_COUNTS:
        for networking in NETWORKING_MODES:
            for pods_per_node in PODS_PER_NODE_OPTIONS:
                max_nodes = None
                # footprint is monotonic non-decreasing in node_count -> early-break scan
                for node_count in NODE_LADDER:
                    if footprint(node_count, pods_per_node, az_count, networking) <= vpc_total_ips:
                        max_nodes = node_count
                    else:
                        break
                if max_nodes is None:
                    continue  # even 1 node doesn't fit -> drop this combination

                total_ips = footprint(max_nodes, pods_per_node, az_count, networking)
                # In-VPC subnets carry 3 reserved AWS IPs each; the custom-networking
                # pod block is external, so only the service block adds to the count.
                in_vpc_subnets = 3 * az_count + (2 if networking == "auto" else 1)
                scenarios.append({
                    "scenario_id": f"az{az_count}-{networking}-{pods_per_node}",
                    "az_count": az_count,
                    "networking": networking,
                    "pods_per_node": pods_per_node,
                    "max_nodes": max_nodes,
                    "total_subnets": 3 * az_count + 2,
                    "total_ips": total_ips,
                    "available_ips": total_ips - 3 * in_vpc_subnets,
                    "vpc_utilization_percent": round(total_ips / vpc_total_ips * 100, 1),
                    "fits": True,
                })

    scenarios.sort(key=lambda s: (-s["vpc_utilization_percent"], s["az_count"], -s["max_nodes"]))

    return {
        "vpc_cidr": str(vpc_network),
        "vpc_total_ips": vpc_total_ips,
        "scenario_count": len(scenarios),
        "scenarios": scenarios[:MAX_SCENARIOS],
    }
