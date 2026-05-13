#!/usr/bin/env python3
"""EKS Subnet Calculator - Core calculation logic."""

import ipaddress
from typing import Dict, List, Any


def parse_cidr(cidr: str) -> ipaddress.IPv4Network:
    """Parse a CIDR string into an IPv4Network object."""
    try:
        return ipaddress.IPv4Network(cidr, strict=False)
    except ValueError as e:
        raise ValueError(f"Invalid CIDR format: {cidr}") from e


def calculate_subnet_size(node_count: int, pods_per_node: int, availability_zones: int) -> int:
    """
    Calculate the required per-AZ subnet size based on node and pod counts.

    Returns the prefix length (e.g., 23 for /23 subnet).
    """
    if availability_zones < 1:
        raise ValueError("availability_zones must be at least 1")
    ips_per_az = node_count * pods_per_node / availability_zones + node_count * 16 / availability_zones + 128

    for prefix in range(24, 8, -1):
        subnet_size = 2 ** (32 - prefix)
        if subnet_size >= ips_per_az:
            return prefix

    return 24


def calculate_pod_cidr_size(node_count: int, pods_per_node: int) -> int:
    """Calculate the pod CIDR prefix needed for all pods across all nodes."""
    total_pods = node_count * pods_per_node
    for prefix in range(24, 8, -1):
        if 2 ** (32 - prefix) >= total_pods:
            return prefix
    return 24


def calculate_control_plane_size() -> int:
    """AWS recommends minimum /28 for control plane subnets."""
    return 28


def calculate_service_cidr(vpc_cidr: str) -> str:
    """Calculate a non-overlapping service CIDR."""
    vpc = parse_cidr(vpc_cidr)
    for cidr in ["10.100.0.0/16", "172.20.0.0/16", "192.168.0.0/16"]:
        if not vpc.overlaps(ipaddress.IPv4Network(cidr, strict=False)):
            return cidr
    return "10.100.0.0/16"


def calculate_pod_cidr(vpc_cidr: str) -> str:
    """Calculate a non-overlapping pod CIDR."""
    vpc = parse_cidr(vpc_cidr)
    for cidr in ["10.200.0.0/16", "172.21.0.0/16", "192.169.0.0/16"]:
        if not vpc.overlaps(ipaddress.IPv4Network(cidr, strict=False)):
            return cidr
    return "10.200.0.0/16"


def calculate_subnets(vpc_cidr: str, availability_zones: int,
                      node_count: int, pods_per_node: int,
                      eks_version: float,
                      pod_cidr: str | None = None) -> Dict[str, Any]:
    """Calculate all subnets for an EKS cluster."""
    if availability_zones < 1 or availability_zones > 6:
        raise ValueError("Availability zones must be between 1 and 6")
    if node_count < 1:
        raise ValueError("Node count must be at least 1")
    if pods_per_node < 1:
        raise ValueError("Pods per node must be at least 1")
    if pod_cidr is not None:
        try:
            parse_cidr(pod_cidr)
        except ValueError:
            raise ValueError(f"Invalid custom Pod CIDR: {pod_cidr}")

    vpc = parse_cidr(vpc_cidr)
    vpc_network = int(vpc.network_address)
    vpc_broadcast = int(vpc.broadcast_address)

    # Validate VPC is large enough
    min_prefix = 32 - (availability_zones * 3 - 1).bit_length()
    if vpc.prefixlen > min_prefix:
        raise ValueError(
            f"VPC CIDR {vpc_cidr} is too small for {availability_zones} AZs. "
            f"Need at least /{min_prefix} or larger."
        )

    subnet_size = calculate_subnet_size(node_count, pods_per_node, availability_zones)
    subnet_ip_count = 2 ** (32 - subnet_size)

    subnets = []
    current_address = vpc_network

    for az_num in range(1, availability_zones + 1):
        az_prefix = f"az{az_num}"

        # Public subnet
        if current_address + subnet_ip_count > vpc_broadcast:
            total_needed = current_address + subnet_ip_count - vpc_network
            raise ValueError(
                f"Insufficient address space for AZ {az_num} {az_prefix}-public. "
                f"Need {subnet_ip_count} IPs but only {vpc_broadcast - current_address + 1} available "
                f"({total_needed} of {vpc_broadcast - vpc_network + 1} total VPC addresses consumed)"
            )
        public_subnet = ipaddress.IPv4Network(
            f"{ipaddress.IPv4Address(current_address)}/{subnet_size}", strict=False
        )
        subnets.append({
            "name": f"{az_prefix}-public",
            "cidr": str(public_subnet),
            "purpose": "public",
            "total_ips": subnet_ip_count,
            "available_ips": subnet_ip_count - 3,
        })
        current_address += subnet_ip_count

        # Private subnet
        if current_address + subnet_ip_count > vpc_broadcast:
            total_needed = current_address + subnet_ip_count - vpc_network
            raise ValueError(
                f"Insufficient address space for AZ {az_num} {az_prefix}-private. "
                f"Need {subnet_ip_count} IPs but only {vpc_broadcast - current_address + 1} available "
                f"({total_needed} of {vpc_broadcast - vpc_network + 1} total VPC addresses consumed)"
            )
        private_subnet = ipaddress.IPv4Network(
            f"{ipaddress.IPv4Address(current_address)}/{subnet_size}", strict=False
        )
        subnets.append({
            "name": f"{az_prefix}-private",
            "cidr": str(private_subnet),
            "purpose": "private",
            "total_ips": subnet_ip_count,
            "available_ips": subnet_ip_count - 3,
        })
        current_address += subnet_ip_count

        # Control plane subnet (/28)
        cp_size = 2 ** (32 - 28)
        if current_address + cp_size > vpc_broadcast:
            total_needed = current_address + cp_size - vpc_network
            raise ValueError(
                f"Insufficient address space for AZ {az_num} {az_prefix}-control-plane. "
                f"Need {cp_size} IPs but only {vpc_broadcast - current_address + 1} available "
                f"({total_needed} of {vpc_broadcast - vpc_network + 1} total VPC addresses consumed)"
            )
        cp_subnet = ipaddress.IPv4Network(
            f"{ipaddress.IPv4Address(current_address)}/28", strict=False
        )
        subnets.append({
            "name": f"{az_prefix}-control-plane",
            "cidr": str(cp_subnet),
            "purpose": "private",
            "total_ips": cp_size,
            "available_ips": cp_size - 3,
        })
        current_address += cp_size

    # Service CIDR — small block for kube-apiserver and core services
    # Align to /20 boundary (4096)
    service_cidr_prefix = 20
    service_size = 2 ** (32 - service_cidr_prefix)
    # Align current_address down to the service CIDR boundary
    aligned = (current_address // service_size) * service_size
    service_cidr = f"{ipaddress.IPv4Address(aligned)}/{service_cidr_prefix}"
    service_network = ipaddress.IPv4Network(service_cidr, strict=True)
    current_address = aligned + service_size

    # Pod CIDR
    if pod_cidr is not None:
        # Custom networking: Pod CIDR is external, doesn't consume VPC space
        pod_network = ipaddress.IPv4Network(pod_cidr, strict=False)
        pod_cidr_str = str(pod_network)
        pod_size = pod_network.num_addresses
        is_custom = True

        # Validate custom Pod CIDR is large enough for all pods
        total_pods = node_count * pods_per_node
        if pod_size < total_pods:
            raise ValueError(
                f"Custom Pod CIDR {pod_cidr} ({pod_size} IPs) is too small for "
                f"{total_pods} pods ({node_count} nodes x {pods_per_node} pods/node)"
            )

        # Validate custom Pod CIDR doesn't overlap with VPC
        if vpc.overlaps(pod_network):
            raise ValueError(
                f"Custom Pod CIDR {pod_cidr} overlaps with VPC {vpc_cidr}. "
                "Use a CIDR range outside the VPC for custom networking."
            )
    else:
        # Auto-generated Pod CIDR — sized to hold all pods across all nodes
        pod_cidr_prefix = calculate_pod_cidr_size(node_count, pods_per_node)
        remaining = vpc_broadcast - current_address + 1
        # If the calculated pod CIDR is larger than remaining space, use the largest power-of-2 that fits
        while (2 ** (32 - pod_cidr_prefix)) > remaining and pod_cidr_prefix < 32:
            pod_cidr_prefix += 1
        # Align to pod CIDR boundary (round up to ensure no overlap with service CIDR)
        pod_size = 2 ** (32 - pod_cidr_prefix)
        # Align up: if current_address isn't on the boundary, move to next boundary
        remainder = current_address % pod_size
        if remainder != 0:
            aligned = current_address + (pod_size - remainder)
        else:
            aligned = current_address
        pod_cidr_str = f"{ipaddress.IPv4Address(aligned)}/{pod_cidr_prefix}"
        pod_network = ipaddress.IPv4Network(pod_cidr_str, strict=True)
        current_address = aligned + pod_size
        is_custom = False

    subnets.append({
        "name": "cluster-service",
        "cidr": service_cidr,
        "purpose": "service",
        "total_ips": service_size,
        "available_ips": service_size - 3,
    })
    subnets.append({
        "name": "cluster-pod",
        "cidr": pod_cidr_str,
        "purpose": "pod",
        "total_ips": pod_size,
        "available_ips": pod_size - 3,
        "custom": is_custom,
    })

    # Validation
    validation = [
        {"passed": subnet_size <= 24, "message": f"Node subnet size is /{subnet_size} (maximum /24)"},
        {"passed": True, "message": "Control plane subnet size >= /28"},
        {"passed": not service_network.overlaps(pod_network),
         "message": "Service and pod CIDRs don't overlap"},
        {"passed": not is_custom or not vpc.overlaps(pod_network),
         "message": f"Pod CIDR {'is custom (external)' if is_custom else 'does not overlap with VPC'}"},
        {"passed": availability_zones >= 2,
         "message": f"Multiple AZs configured ({availability_zones} AZs)"},
        {"passed": eks_version >= 1.21,
         "message": f"EKS version supports ENI trunking ({eks_version})"},
    ]

    total_ips = sum(s["total_ips"] for s in subnets)
    available_ips = sum(s["available_ips"] for s in subnets)
    vpc_total = vpc_broadcast - vpc_network + 1
    vpc_used = sum(s["total_ips"] for s in subnets if not s.get("custom", False))

    return {
        "vpc_cidr": vpc_cidr,
        "availability_zones": availability_zones,
        "node_count": node_count,
        "pods_per_node": pods_per_node,
        "pod_cidr": pod_cidr,
        "eks_version": eks_version,
        "subnets": subnets,
        "validation": validation,
        "summary": {
            "total_subnets": len(subnets),
            "total_ips": total_ips,
            "available_ips": available_ips,
            "vpc_used": vpc_used,
            "vpc_total": vpc_total,
            "vpc_utilization_percent": round(vpc_used / vpc_total * 100, 1),
        }
    }