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

## Usage

### Running Locally

1. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

2. **Start the Flask development server:**

   ```bash
   python app.py
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

5. **Stop the server:**

   Press `Ctrl+C` in the terminal.

### Running with Docker

```bash
docker build -t eks-subnet-calculator .
docker run -p 8080:8080 eks-subnet-calculator
open http://localhost:8080
```

## Input Parameters

| Parameter | Description |
|-----------|-------------|
| VPC CIDR | Your VPC's IPv4 CIDR block (e.g., 10.0.0.0/16). Must be /16 or smaller (e.g., /15, /16, /24). |
| Availability Zones | Number of AZs for high availability (1-6) |
| Total Node Count | Total estimated number of worker nodes across all AZs |
| Pods Per Node | Maximum number of pods scheduled on each node (default: 110) |
| Custom Pod CIDR | Optional custom CIDR for pod networking (e.g., 100.64.0.0/10). When set, pod IPs are allocated outside the VPC. |
| EKS Version | Kubernetes version for the cluster |

## Output

The calculator generates:

- **Public Subnets** - One per AZ for load balancers
- **Private Subnets** - One per AZ for worker nodes
- **Control Plane Subnets** - One per AZ for EKS control plane
- **Service CIDR** - For Kubernetes services (allocated within the VPC)
- **Pod CIDR** - For pod networking (auto-generated or custom)

## Custom Pod CIDR

Enable "Use custom Pod CIDR" to allocate pod IPs outside the VPC address space. This is useful for:

- **CG-NAT** (100.64.0.0/10 or 198.19.0.0/16): Free up RFC1918 VPC IPs for other workloads
- **Large clusters**: Avoid exhausting VPC address space with pod IPs
- **Multi-VPC setups**: Use a dedicated CIDR for pod networking

When custom networking is enabled, the Pod CIDR is validated to ensure it doesn't overlap with the VPC and is large enough to hold all pods.

## AWS Best Practices

The calculator enforces:

- Node subnet size <= /24 (smaller prefix = larger subnet for more pods)
- Control plane subnet size >= /28
- Non-overlapping service and pod CIDRs
- Custom Pod CIDR doesn't overlap with VPC
- Minimum 2 AZs recommended for production

## Development

```bash
pytest test_subnet_calculator.py test_validators.py -v
```