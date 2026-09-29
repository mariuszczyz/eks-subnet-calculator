# EKS Subnet Calculator

A browser-based tool to help SRE engineers and IT architects plan CIDR subnet allocations for AWS EKS clusters.

## Features

- Interactive subnet planning for AWS EKS clusters
- Real-time CIDR hierarchy visualization
- AWS best practices validation
- Support for 1-6 availability zones
- Automatic subnet size calculation based on node count and pods per node
- Custom Pod CIDR support (e.g., 100.64.0.0/10 CG-NAT) to avoid consuming VPC IPs for pods
- VPC utilization tracking
- **EKS Subnet Planner**: Given a VPC CIDR, enumerate all cluster scenarios (AZs × networking mode × pods-per-node combinations) that fit inside the VPC

## Usage

### Running Locally

1. **Create a virtual environment and install dependencies:**

   ```bash
   uv venv
   uv pip install -r requirements.txt
   ```

2. **Start the Flask development server:**

   ```bash
   uv run python app.py
   ```

   The server starts at `http://localhost:5555` by default. You'll see output like:

   ```
   * Serving Flask app 'app'
   * Debug mode: on
   * Running on http://0.0.0.0:5555
   ```

3. **Open the app in your browser:**

   ```bash
   open http://localhost:5555
   ```

4. **Verify it's working:**

   ```bash
   curl http://localhost:5555/ | head -5
   ```

   Or test the API directly:

   ```bash
   curl -X POST http://localhost:5555/api/calculate \
     -H "Content-Type: application/json" \
     -d '{"vpc_cidr": "10.0.0.0/16", "availability_zones": 2, "node_count": 10, "pods_per_node": 110, "eks_version": 1.27}'
   ```

5. **Use the EKS Subnet Planner:**

   Navigate to `http://localhost:5555/planner` and enter a VPC CIDR (e.g., `10.0.0.0/16`) to see cluster scenarios grouped by availability-zone count, with each group showing cards for the number of configurations that fit.

   ```bash
   curl -X POST http://localhost:5555/api/plan \
     -H "Content-Type: application/json" \
     -d '{"vpc_cidr": "10.0.0.0/16"}'
   ```

6. **Stop the server:**

   Press `Ctrl+C` in the terminal.

### Running with Docker

```bash
docker build -t eks-subnet-calculator .
docker run -p 8080:8080 eks-subnet-calculator
open http://localhost:8080
```

## Input Parameters

The calculator accepts these inputs:

| Parameter | Description |
|-----------|-------------|
| VPC CIDR | Your VPC's IPv4 CIDR block (e.g., 10.0.0.0/16). The Planner accepts any IPv4 prefix from /8 through /28. |
| Availability Zones | Number of AZs for high availability (1-6) |
| Total Node Count | Total estimated number of worker nodes across all AZs |
| Pods Per Node | Maximum number of pods scheduled on each node (default: 110) |
| Custom Pod CIDR | Optional custom CIDR for pod networking (e.g., 100.64.0.0/10). When set, pod IPs are allocated outside the VPC. |
| EKS Version | Kubernetes version for the cluster |

## Output

### Calculator (POST /api/calculate)

The calculator generates:

- **Public Subnets** - One per AZ for load balancers
- **Private Subnets** - One per AZ for worker nodes
- **Control Plane Subnets** - One per AZ for EKS control plane
- **Service CIDR** - For Kubernetes services (allocated within the VPC)
- **Pod CIDR** - For pod networking (auto-generated or custom)

### Planner (POST /api/plan)

The planner returns a JSON object with scenario enumeration:

```json
{
  "vpc_cidr": "10.0.0.0/16",
  "vpc_total_ips": 65536,
  "scenario_count": 48,
  "scenarios": [
    {
      "scenario_id": "az1-auto-250",
      "az_count": 1,
      "networking": "auto",
      "pods_per_node": 250,
      "max_nodes": 128,
      "total_subnets": 3,
      "total_ips": 65536,
      "available_ips": 64960,
      "vpc_utilization_percent": 100.0,
      "fits": true
    }
  ]
}
```

**Scenario table columns (per group card):**

| Column | Description |
|--------|-------------|
| Networking | Pod CIDR mode: `auto` (Kubernetes-managed within VPC) or `custom` (external CG-NAT) |
| Pods/Node | Pods per node configuration (25, 50, 110, or 250) |
| Max Nodes | Maximum worker nodes that fit within the VPC for this scenario |
| Total Subnets | Sum of public + private node subnets + control plane (3 × AZs + 2) |
| Total IPs | VPC IP consumption for this scenario (including alignment headroom) |
| Available IPs | Total IPs minus 3 × AZs for AWS reserved addresses per subnet |
| VPC Utilization % | Percentage of the VPC used by this scenario |

### Networking Modes Explained

**Auto (Kubernetes-managed):**
- Pod CIDR allocated automatically by Kubernetes inside the VPC
- Standard for most EKS deployments
- Both pods and nodes consume VPC IP address space

**Custom:**
- Pod CIDR specified by user (e.g., 100.64.0.0/10)
- Pod IPs allocated outside the VPC via CG-NAT
- Frees up RFC1918 VPC IPs for other workloads
- Ideal for large clusters or multi-VPC setups

## AWS Best Practices

The calculator enforces:

- Node subnet size <= /24 (smaller prefix = larger subnet for more pods)
- Control plane subnet size >= /28
- Non-overlapping service and pod CIDRs
- Custom Pod CIDR doesn't overlap with VPC
- Minimum 2 AZs recommended for production

## EKS Subnet Planner Features

The planner provides a reverse-engineering view: given only a VPC CIDR, it determines which cluster configurations are feasible.

**How it works:**
1. Accepts any valid IPv4 prefix from /8 through /28
2. Enumerates 48 scenarios (6 AZs × 2 networking modes × 4 pods-per-node options)
3. Groups results by AZ count (ascending: 1, 2, 3...) with per-group cards
4. Each group shows cards for the number of configurations that fit (8 options per AZ tier)
5. Inside each group, a table displays scenarios sorted by VPC utilization (%), then max nodes
6. Group headers use labels: "1 AZ — Single-AZ, non-HA" (HA badge), "2 AZs — Highly available control plane" (HA badge), "3+ AZs — Full regional resilience" (Full Resilience badge)

**Use cases:**
- Planning capacity before committing to a VPC allocation
- Understanding tradeoffs between pod density and cluster scale
- Evaluating whether CG-NAT (custom networking) provides benefit for your VPC size

## Development

### Test suite

Run the test suite:

```bash
pytest test_subnet_calculator.py test_validators.py -v
```

Run the subnet planner tests:

```bash
pytest test_subnet_planner.py -v
```

To lint code:

```bash
flake8 subnet_planner.py app.py
```
