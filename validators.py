#!/usr/bin/env python3
"""Input validators for the EKS Subnet Calculator."""

import re
import ipaddress
from typing import Tuple, Optional


def is_valid_cidr(cidr: str) -> Tuple[bool, Optional[str]]:
    if not cidr:
        return False, "CIDR is required"
    pattern = r'^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})/(\d{1,2})$'
    match = re.match(pattern, cidr)
    if not match:
        return False, "Invalid CIDR format. Use format like 10.0.0.0/16"
    octets = [int(g) for g in match.groups()[:4]]
    prefix = int(match.group(5))
    for i, octet in enumerate(octets):
        if octet > 255:
            return False, f"Invalid octet {octet} at position {i + 1}"
    if prefix < 0 or prefix > 32:
        return False, "CIDR prefix must be between 0 and 32"
    try:
        ipaddress.IPv4Network(cidr, strict=True)
    except ValueError:
        return False, "Invalid network address for the given prefix"
    return True, None


def is_valid_vpc_cidr(cidr: str) -> Tuple[bool, Optional[str]]:
    is_valid, error = is_valid_cidr(cidr)
    if not is_valid:
        return is_valid, error
    network = ipaddress.IPv4Network(cidr, strict=False)
    if network.prefixlen > 28:
        return False, "VPC CIDR must be /28 or smaller (prefix too large)."
    return True, None


def is_valid_az_count(count: int) -> Tuple[bool, Optional[str]]:
    if count < 1:
        return False, "At least 1 availability zone is required"
    if count > 6:
        return False, "Maximum 6 availability zones supported"
    return True, None


def is_valid_node_count(count: int) -> Tuple[bool, Optional[str]]:
    if count < 1:
        return False, "Node count must be at least 1"
    if count > 10000:
        return False, "Node count exceeds maximum (10000)"
    return True, None


def is_valid_pods_per_node(count: int) -> Tuple[bool, Optional[str]]:
    if count < 1:
        return False, "Pods per node must be at least 1"
    if count > 1000:
        return False, "Pods per node exceeds maximum (1000)"
    return True, None


def is_valid_eks_version(version: float) -> Tuple[bool, Optional[str]]:
    valid_versions = [1.28, 1.29, 1.30, 1.31, 1.32]
    if version not in valid_versions:
        return False, f"Invalid EKS version. Supported: {', '.join(f'{v:.2f}' for v in valid_versions)}"
    return True, None


def is_valid_pod_cidr(pod_cidr: str, vpc_cidr: str | None = None) -> Tuple[bool, Optional[str]]:
    """Validate a custom Pod CIDR."""
    if not pod_cidr:
        return True, None  # None means auto (no custom CIDR)
    try:
        ipaddress.IPv4Network(pod_cidr, strict=False)
    except ValueError:
        return False, f"Invalid Pod CIDR format: {pod_cidr}"

    if vpc_cidr and pod_cidr:
        vpc = ipaddress.IPv4Network(vpc_cidr, strict=False)
        pod = ipaddress.IPv4Network(pod_cidr, strict=False)
        if vpc.overlaps(pod):
            return False, f"Pod CIDR {pod_cidr} overlaps with VPC {vpc_cidr}"

    return True, None


def validate_cluster_config(vpc_cidr: str, az_count: int,
                            node_count: int, pods_per_node: int,
                            eks_version: float,
                            pod_cidr: str | None = None) -> Tuple[bool, Optional[str]]:
    for validator, value in [
        (lambda: is_valid_vpc_cidr(vpc_cidr), vpc_cidr),
        (lambda: is_valid_az_count(az_count), az_count),
        (lambda: is_valid_node_count(node_count), node_count),
        (lambda: is_valid_pods_per_node(pods_per_node), pods_per_node),
        (lambda: is_valid_pod_cidr(pod_cidr, vpc_cidr), pod_cidr),
        (lambda: is_valid_eks_version(eks_version), eks_version),
    ]:
        is_valid, error = validator()
        if not is_valid:
            return False, error
    return True, None