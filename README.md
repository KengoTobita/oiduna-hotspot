# oiduna-hotspot

**Ubuntu Desktop Wi-Fi Hotspot Setup for Oiduna**

This extension automatically configures Ubuntu Desktop as a Wi-Fi access point with local DNS, enabling network-based Oiduna deployments.

---

## When You Need This Extension

✅ **You NEED this extension if:**
- Your **Distribution (DSL)** runs on a **separate PC** from Oiduna
- You want to connect Distribution clients via **Wi-Fi or Ethernet** to the Oiduna server
- You need **local DNS** (e.g., `oiduna.local`) for easy client access

❌ **You DON'T need this extension if:**
- Distribution and Oiduna run on the **same PC** (single-machine setup)
- You're using Oiduna locally with `localhost` or `127.0.0.1`

---

## Use Case Example

```
┌─────────────────────────────────┐
│ Client PC (Distribution)        │
│  - MARS DSL / TidalCycles       │
│  - Sends patterns via HTTP      │
└────────────┬────────────────────┘
             │ Wi-Fi "Oiduna-Network"
             ↓
┌─────────────────────────────────┐
│ Ubuntu PC (Oiduna Server)       │
│  - Wi-Fi Hotspot (this tool)    │
│  - Oiduna API                   │
│  - SuperDirt / MIDI devices     │
└─────────────────────────────────┘
```

---

## Features

- 🌐 **Wi-Fi Access Point** - Ubuntu PC becomes a wireless router
- 🔍 **Local DNS** - Access Oiduna via `oiduna.local` instead of IP addresses
- 🔗 **NAT/IP Forwarding** - Share internet connection with clients (optional)
- 📡 **DHCP Server** - Automatic IP address assignment
- ⚙️ **3 Network Modes** - Wi-Fi only, Ethernet only, or Bridge mode
- 🐍 **Automated Setup** - Single Python script configures everything

---

## Requirements

### Platform
- **Ubuntu Desktop 24.04 LTS** (or compatible)
- Wi-Fi adapter with **AP mode support** (for Wi-Fi modes)
- Ethernet adapter (for Ethernet/Bridge modes)

### Check Wi-Fi AP Support
```bash
iw list | grep -A 10 "Supported interface modes"
# Look for "* AP" in the output
```

### Dependencies (auto-installed)
- NetworkManager
- dnsmasq-base
- bridge-utils (for bridge mode only)
- Python 3.13+
- pyyaml

---

## Network Modes

### Mode 1: Wi-Fi Only (Default)
Ubuntu PC creates a Wi-Fi hotspot. Clients connect via Wi-Fi.

**Use case:** Most common scenario, wireless clients only

### Mode 2: Ethernet Only
Ubuntu PC provides wired LAN via Ethernet adapter. No Wi-Fi used.

**Use case:** Wired-only environments, Wi-Fi not available

### Mode 3: Bridge (Wi-Fi + Ethernet)
Wi-Fi and Ethernet are bridged into a single network. All clients share the same subnet.

**Use case:** Mixed wireless and wired clients need to communicate

---

## Installation

### 1. Clone this repository
```bash
cd /path/to/your/workspace
git clone <repository-url> oiduna-hotspot
cd oiduna-hotspot
```

### 2. Install Python dependencies
```bash
# Using uv (recommended)
uv sync

# Or using pip
pip install -r requirements.txt
```

---

## Configuration

Edit `network_config.yaml` to customize your network settings:

```yaml
mode: "wifi_only"                # wifi_only, ethernet_only, bridge
ssid: "Oiduna-Network"           # Wi-Fi network name
password: "your-strong-password" # Wi-Fi password (8+ characters)
subnet: "10.42.0.0/24"           # Subnet for clients
gateway_ip: "10.42.0.1"          # Ubuntu PC IP address
local_hostnames:
  - "oiduna.local"               # DNS hostnames
  - "oiduna-server.local"
upstream_interface: "eth0"       # Internet connection (optional)
wifi_interface: "wlan0"          # Wi-Fi adapter name
ethernet_interface: "eth1"       # Ethernet adapter name (for ethernet_only/bridge)
```

**Find your interface names:**
```bash
ip link
# Example output:
# 2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> ...    ← Upstream internet
# 3: wlan0: <BROADCAST,MULTICAST> ...               ← Wi-Fi adapter
# 4: eth1: <BROADCAST,MULTICAST> ...                ← Client ethernet
```

---

## Usage

### Setup Network
```bash
sudo python setup_network.py --config network_config.yaml
```

The script will:
1. Check root permissions
2. Verify Wi-Fi AP support (if needed)
3. Install missing packages
4. Enable IP forwarding
5. Configure NAT/iptables
6. Set up local DNS
7. Create Wi-Fi hotspot (Wi-Fi modes)

### Teardown (Rollback)
```bash
sudo python setup_network.py --teardown
```

This removes:
- Wi-Fi hotspot
- Local DNS configuration
- NAT rules
- Bridge interfaces (if applicable)

---

## Verify Setup

### 1. Connect from client PC
Connect to the Wi-Fi network "Oiduna-Network" (or Ethernet cable for wired mode)

### 2. Test DNS resolution
```bash
ping oiduna.local
# Should resolve to 10.42.0.1 (or your configured gateway_ip)
```

### 3. Test Oiduna API access
```bash
curl http://oiduna.local:57122/health
# → {"status": "ok"}
```

---

## File Structure (Proposed)

```
oiduna-hotspot/
├── README.md                    # This file
├── NETWORK_SETUP.md             # Detailed setup guide (to be migrated)
├── setup_network.py             # Main setup script (to be migrated)
├── network_config.yaml          # Default configuration (to be migrated)
├── examples/                    # Configuration examples
│   ├── wifi_only.yaml
│   ├── ethernet_only.yaml
│   └── bridge.yaml
├── pyproject.toml               # Python dependencies
├── requirements.txt             # Alternative dependency file
└── tests/                       # Test suite (future)
```

---

## Troubleshooting

### Wi-Fi adapter doesn't support AP mode
```bash
iw list | grep -A 10 "Supported interface modes"
# If "* AP" is missing, you need a different Wi-Fi adapter
# Recommended chipsets: Atheros AR9271, Realtek RTL8812AU
```

### Hotspot won't start
```bash
# Check NetworkManager status
sudo systemctl status NetworkManager

# Check dnsmasq logs
sudo journalctl -u dnsmasq -f
```

### Clients can't resolve oiduna.local
```bash
# On client, check DNS server
cat /etc/resolv.conf
# Should contain: nameserver 10.42.0.1

# On server, check dnsmasq config
cat /etc/NetworkManager/dnsmasq-shared.d/oiduna-local-dns.conf
```

### Port 57122 unreachable from client
```bash
# On Oiduna server, check firewall
sudo ufw status

# Allow Oiduna API port
sudo ufw allow 57122/tcp

# Verify Oiduna is listening on all interfaces
# In Oiduna .env file:
API_HOST=0.0.0.0
API_PORT=57122
```

---

## Oiduna Configuration

After network setup, configure Oiduna to listen on all interfaces:

```bash
# In /path/to/oiduna/.env
API_HOST=0.0.0.0       # Listen on all interfaces (not just localhost)
API_PORT=57122
OSC_HOST=127.0.0.1     # SuperDirt stays on localhost
OSC_PORT=57120
```

---

## Security Considerations

⚠️ **Important Security Notes:**

1. **Strong Wi-Fi Password** - Use 12+ characters with mixed alphanumeric and symbols
2. **Firewall Rules** - Only open necessary ports (57122 for Oiduna API)
3. **No Authentication** - Oiduna API currently has no authentication. Use in trusted networks only.
4. **HTTPS** - Consider adding HTTPS for production (use Nginx/Caddy as reverse proxy)

---

## Related Projects

- **[Oiduna](../oiduna)** - Core loop engine and API
- **[MARS for Oiduna](../MARS_for_oiduna)** - Distribution (DSL) for Oiduna

---

## License

MIT

---

## Contributing

Contributions welcome! Please:
1. Test on Ubuntu Desktop 24.04 LTS
2. Document any new configuration options
3. Update this README with new features

---

## Version

**Version:** 0.1.0 (Initial Release)
**Last Updated:** 2026-02-25
**Compatible with:** Oiduna v1.0+

---

## Questions?

For issues or questions:
- Check [NETWORK_SETUP.md](./NETWORK_SETUP.md) for detailed setup guide
- Open an issue on GitHub
- Refer to Oiduna main documentation
