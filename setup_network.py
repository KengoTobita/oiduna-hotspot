#!/usr/bin/env python3
"""
Oiduna Hotspot - Network Setup Script

Ubuntu PCをWi-Fiアクセスポイント化し、ローカルDNSを提供するための自動セットアップスクリプト。
3つのモードをサポート: wifi_only, ethernet_only, bridge

TODO: Future Auto-Detection Feature
------------------------------------
将来的には、PCの利用可能なネットワークインターフェースを自動検出し、
Wi-FiとEthernetの両方が利用可能な場合は自動的にbridgeモードを有効化する。
現在は設定ファイルで明示的にモードを指定する必要がある。

Usage:
    sudo python setup_network.py --config network_config.yaml
    sudo python setup_network.py --teardown
"""

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

try:
    import yaml
except ImportError:
    print("Error: pyyaml is required. Install with: pip install pyyaml")
    sys.exit(1)

try:
    from pyroute2 import IPRoute
    HAS_PYROUTE2 = True
except ImportError:
    HAS_PYROUTE2 = False

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

NetworkMode = Literal["wifi_only", "ethernet_only", "bridge"]


class NetworkSetup:
    """ネットワークセットアップの自動化クラス"""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.mode: NetworkMode = config.get("mode", "wifi_only")
        self.ssid = config.get("ssid", "Oiduna-Network")
        self.password = config.get("password", "")
        self.subnet = config.get("subnet", "10.42.0.0/24")
        self.gateway_ip = config.get("gateway_ip", "10.42.0.1")
        self.local_hostnames = config.get("local_hostnames", ["oiduna.local"])
        self.upstream_interface = config.get("upstream_interface", "eth0")
        self.wifi_interface = config.get("wifi_interface", "wlan0")
        self.ethernet_interface = config.get("ethernet_interface", "eth1")
        self.bridge_interface = "br0"

        # モードバリデーション
        if self.mode not in ["wifi_only", "ethernet_only", "bridge"]:
            logger.error(f"無効なモード: {self.mode}")
            logger.error("有効なモード: wifi_only, ethernet_only, bridge")
            sys.exit(1)

    def check_root(self):
        """root権限チェック"""
        if os.geteuid() != 0:
            logger.error("このスクリプトはroot権限で実行する必要があります。sudo を使用してください。")
            sys.exit(1)
        logger.info("✓ root権限を確認しました")

    def check_wifi_ap_support(self):
        """Wi-FiアダプタのAPモード対応チェック"""
        if self.mode == "ethernet_only":
            logger.info("ethernet_onlyモードのため、Wi-Fi APチェックをスキップします")
            return

        logger.info(f"Wi-Fiアダプタ {self.wifi_interface} のAPモード対応を確認中...")
        try:
            result = subprocess.run(
                ["iw", "list"],
                capture_output=True,
                text=True,
                check=True,
            )
            if "* AP" not in result.stdout:
                logger.error(f"Wi-Fiアダプタ {self.wifi_interface} はAPモードに対応していません")
                logger.error("APモード対応のWi-Fiアダプタが必要です")
                sys.exit(1)
            logger.info(f"✓ Wi-Fiアダプタ {self.wifi_interface} はAPモード対応です")
        except subprocess.CalledProcessError as e:
            logger.error(f"Wi-Fiアダプタの確認に失敗しました: {e}")
            sys.exit(1)
        except FileNotFoundError:
            logger.error("iwコマンドが見つかりません。wireless-toolsをインストールしてください。")
            logger.error("sudo apt install wireless-tools iw")
            sys.exit(1)

    def check_packages(self):
        """必要なパッケージの確認"""
        logger.info("必要なパッケージの確認中...")
        packages = ["NetworkManager", "dnsmasq-base"]

        # bridgeモードの場合はbridge-utilsも必要
        if self.mode == "bridge":
            packages.append("bridge-utils")

        missing_packages = []

        for package in packages:
            try:
                result = subprocess.run(
                    ["dpkg", "-l", package],
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    missing_packages.append(package)
            except Exception:
                missing_packages.append(package)

        if missing_packages:
            logger.warning(f"以下のパッケージがインストールされていません: {', '.join(missing_packages)}")
            logger.info("インストールを試みます...")
            try:
                subprocess.run(
                    ["apt", "update"],
                    check=True,
                )
                subprocess.run(
                    ["apt", "install", "-y"] + missing_packages,
                    check=True,
                )
                logger.info("✓ パッケージのインストールが完了しました")
            except subprocess.CalledProcessError as e:
                logger.error(f"パッケージのインストールに失敗しました: {e}")
                sys.exit(1)
        else:
            logger.info("✓ 必要なパッケージがすべてインストールされています")

    def enable_ip_forwarding(self):
        """IPフォワーディングの有効化"""
        logger.info("IPフォワーディングを有効化中...")
        try:
            # 一時的に有効化
            subprocess.run(
                ["sysctl", "-w", "net.ipv4.ip_forward=1"],
                check=True,
                capture_output=True,
            )

            # /etc/sysctl.confに永続化
            sysctl_conf = Path("/etc/sysctl.conf")
            content = sysctl_conf.read_text() if sysctl_conf.exists() else ""

            if "net.ipv4.ip_forward=1" not in content:
                with sysctl_conf.open("a") as f:
                    f.write("\n# Oiduna Network Setup: Enable IP forwarding\n")
                    f.write("net.ipv4.ip_forward=1\n")
                logger.info("✓ IPフォワーディングを永続化しました")
            else:
                logger.info("✓ IPフォワーディングは既に設定されています")

        except subprocess.CalledProcessError as e:
            logger.error(f"IPフォワーディングの有効化に失敗しました: {e}")
            sys.exit(1)

    def setup_nat(self, internal_interface: str):
        """NAT（マスカレード）設定"""
        logger.info(f"NAT（マスカレード）を設定中... (internal: {internal_interface}, upstream: {self.upstream_interface})")
        try:
            # 既存のルールをクリア（慎重に）
            subprocess.run(
                ["iptables", "-t", "nat", "-F"],
                check=True,
                capture_output=True,
            )

            # NAT設定
            subprocess.run(
                ["iptables", "-t", "nat", "-A", "POSTROUTING", "-o", self.upstream_interface, "-j", "MASQUERADE"],
                check=True,
                capture_output=True,
            )

            # フォワーディングルール
            subprocess.run(
                ["iptables", "-A", "FORWARD", "-i", internal_interface, "-o", self.upstream_interface, "-j", "ACCEPT"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["iptables", "-A", "FORWARD", "-i", self.upstream_interface, "-o", internal_interface, "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"],
                check=True,
                capture_output=True,
            )

            # 設定を永続化
            try:
                subprocess.run(
                    ["netfilter-persistent", "save"],
                    check=True,
                    capture_output=True,
                )
                logger.info("✓ NAT設定を永続化しました")
            except FileNotFoundError:
                logger.warning("netfilter-persistentが見つかりません。iptables-persistentをインストールしてください。")
                logger.warning("sudo apt install iptables-persistent")
                logger.warning("NAT設定は再起動後に失われます。")

        except subprocess.CalledProcessError as e:
            logger.error(f"NAT設定に失敗しました: {e}")
            sys.exit(1)

    def setup_local_dns(self, bind_interface: str):
        """ローカルDNS設定"""
        logger.info(f"ローカルDNSを設定中... (bind: {bind_interface})")
        dnsmasq_dir = Path("/etc/NetworkManager/dnsmasq-shared.d")
        dnsmasq_conf = dnsmasq_dir / "oiduna-local-dns.conf"

        try:
            # ディレクトリ作成
            dnsmasq_dir.mkdir(parents=True, exist_ok=True)

            # dnsmasq設定ファイル生成
            with dnsmasq_conf.open("w") as f:
                f.write("# Oiduna Network Setup: Local DNS records\n")
                f.write(f"# Mode: {self.mode}\n")
                f.write(f"interface={bind_interface}\n")
                for hostname in self.local_hostnames:
                    f.write(f"address=/{hostname}/{self.gateway_ip}\n")

            logger.info(f"✓ ローカルDNS設定を作成しました: {dnsmasq_conf}")

            # NetworkManager再起動
            subprocess.run(
                ["systemctl", "restart", "NetworkManager"],
                check=True,
                capture_output=True,
            )
            logger.info("✓ NetworkManagerを再起動しました")

        except Exception as e:
            logger.error(f"ローカルDNS設定に失敗しました: {e}")
            sys.exit(1)

    def create_hotspot(self):
        """NetworkManagerホットスポット作成"""
        logger.info(f"ホットスポット '{self.ssid}' を作成中...")
        try:
            # 既存のホットスポット接続を削除
            result = subprocess.run(
                ["nmcli", "connection", "show"],
                capture_output=True,
                text=True,
            )
            if "Hotspot" in result.stdout:
                logger.info("既存のホットスポット接続を削除中...")
                subprocess.run(
                    ["nmcli", "connection", "delete", "Hotspot"],
                    capture_output=True,
                )

            # ホットスポット作成
            cmd = [
                "nmcli", "device", "wifi", "hotspot",
                "ssid", self.ssid,
                "password", self.password,
                "ifname", self.wifi_interface,
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            logger.info(f"✓ ホットスポット '{self.ssid}' を作成しました")

        except subprocess.CalledProcessError as e:
            logger.error(f"ホットスポットの作成に失敗しました: {e}")
            logger.error(f"stderr: {e.stderr.decode() if e.stderr else 'N/A'}")
            sys.exit(1)

    def create_bridge(self):
        """ブリッジインターフェース作成"""
        logger.info(f"ブリッジ '{self.bridge_interface}' を作成中...")

        if HAS_PYROUTE2:
            self._create_bridge_pyroute2()
        else:
            self._create_bridge_ip_commands()

    def _create_bridge_pyroute2(self):
        """pyroute2を使用したブリッジ作成"""
        try:
            ip = IPRoute()

            # 既存のブリッジを削除
            try:
                br_idx = ip.link_lookup(ifname=self.bridge_interface)
                if br_idx:
                    ip.link("del", index=br_idx[0])
                    logger.info(f"既存のブリッジ {self.bridge_interface} を削除しました")
            except Exception:
                pass

            # ブリッジ作成
            ip.link("add", ifname=self.bridge_interface, kind="bridge")
            br_idx = ip.link_lookup(ifname=self.bridge_interface)[0]
            logger.info(f"✓ ブリッジ {self.bridge_interface} を作成しました")

            # Wi-Fiインターフェースをブリッジに追加
            wifi_idx = ip.link_lookup(ifname=self.wifi_interface)[0]
            ip.link("set", index=wifi_idx, master=br_idx)
            logger.info(f"✓ {self.wifi_interface} をブリッジに追加しました")

            # Ethernetインターフェースをブリッジに追加
            eth_idx = ip.link_lookup(ifname=self.ethernet_interface)[0]
            ip.link("set", index=eth_idx, master=br_idx)
            logger.info(f"✓ {self.ethernet_interface} をブリッジに追加しました")

            # ブリッジを有効化
            ip.link("set", index=br_idx, state="up")
            logger.info(f"✓ ブリッジ {self.bridge_interface} を有効化しました")

            # ブリッジにIPアドレスを割り当て
            subnet_parts = self.subnet.split("/")
            ip.addr("add", index=br_idx, address=self.gateway_ip, prefixlen=int(subnet_parts[1]))
            logger.info(f"✓ ブリッジに IP {self.gateway_ip}/{subnet_parts[1]} を割り当てました")

            ip.close()

        except Exception as e:
            logger.error(f"pyroute2によるブリッジ作成に失敗しました: {e}")
            sys.exit(1)

    def _create_bridge_ip_commands(self):
        """ipコマンドを使用したブリッジ作成"""
        try:
            # 既存のブリッジを削除
            subprocess.run(
                ["ip", "link", "delete", self.bridge_interface],
                capture_output=True,
            )

            # ブリッジ作成
            subprocess.run(
                ["ip", "link", "add", self.bridge_interface, "type", "bridge"],
                check=True,
                capture_output=True,
            )
            logger.info(f"✓ ブリッジ {self.bridge_interface} を作成しました")

            # Wi-Fiインターフェースをブリッジに追加
            subprocess.run(
                ["ip", "link", "set", self.wifi_interface, "master", self.bridge_interface],
                check=True,
                capture_output=True,
            )
            logger.info(f"✓ {self.wifi_interface} をブリッジに追加しました")

            # Ethernetインターフェースをブリッジに追加
            subprocess.run(
                ["ip", "link", "set", self.ethernet_interface, "master", self.bridge_interface],
                check=True,
                capture_output=True,
            )
            logger.info(f"✓ {self.ethernet_interface} をブリッジに追加しました")

            # ブリッジを有効化
            subprocess.run(
                ["ip", "link", "set", self.bridge_interface, "up"],
                check=True,
                capture_output=True,
            )
            logger.info(f"✓ ブリッジ {self.bridge_interface} を有効化しました")

            # ブリッジにIPアドレスを割り当て
            subprocess.run(
                ["ip", "addr", "add", f"{self.gateway_ip}/{self.subnet.split('/')[1]}", "dev", self.bridge_interface],
                check=True,
                capture_output=True,
            )
            logger.info(f"✓ ブリッジに IP {self.gateway_ip} を割り当てました")

        except subprocess.CalledProcessError as e:
            logger.error(f"ipコマンドによるブリッジ作成に失敗しました: {e}")
            sys.exit(1)

    def setup_ethernet_lan(self):
        """Ethernet単体LANのセットアップ"""
        logger.info(f"Ethernet LAN ({self.ethernet_interface}) のセットアップ中...")

        try:
            # Ethernetインターフェースにスタティックipを設定
            subprocess.run(
                ["ip", "addr", "flush", "dev", self.ethernet_interface],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["ip", "addr", "add", f"{self.gateway_ip}/{self.subnet.split('/')[1]}", "dev", self.ethernet_interface],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["ip", "link", "set", self.ethernet_interface, "up"],
                check=True,
                capture_output=True,
            )
            logger.info(f"✓ {self.ethernet_interface} に IP {self.gateway_ip} を設定しました")

        except subprocess.CalledProcessError as e:
            logger.error(f"Ethernet LAN設定に失敗しました: {e}")
            sys.exit(1)

    def setup(self):
        """セットアップメイン処理"""
        logger.info(f"=== Oiduna Network Setup 開始 (モード: {self.mode}) ===")

        self.check_root()
        self.check_packages()

        if self.mode == "wifi_only":
            self.check_wifi_ap_support()
            self.enable_ip_forwarding()
            self.setup_nat(self.wifi_interface)
            self.setup_local_dns(self.wifi_interface)
            self.create_hotspot()

        elif self.mode == "ethernet_only":
            self.enable_ip_forwarding()
            self.setup_ethernet_lan()
            self.setup_nat(self.ethernet_interface)
            self.setup_local_dns(self.ethernet_interface)

        elif self.mode == "bridge":
            self.check_wifi_ap_support()
            self.enable_ip_forwarding()
            self.create_bridge()
            self.setup_nat(self.bridge_interface)
            self.setup_local_dns(self.bridge_interface)
            # ブリッジモードではホットスポットは手動設定が必要
            logger.warning("ブリッジモードでは、Wi-Fi APの設定を別途行う必要があります")
            logger.warning("hostapd.confに 'bridge=br0' を追加してください")

        logger.info("=== Oiduna Network Setup 完了 ===")
        logger.info("")
        logger.info("次のステップ:")

        if self.mode == "wifi_only":
            logger.info(f"1. クライアントPCからWi-Fi '{self.ssid}' に接続してください")
            logger.info(f"2. パスワード: {self.password}")
        elif self.mode == "ethernet_only":
            logger.info(f"1. クライアントPCをEthernetケーブルで {self.ethernet_interface} に接続してください")
        elif self.mode == "bridge":
            logger.info(f"1. クライアントPCをWi-Fi '{self.ssid}' またはEthernet経由で接続してください")
            logger.info(f"2. Wi-Fiパスワード: {self.password}")

        logger.info("3. Oiduna APIを起動してください:")
        logger.info("   cd /path/to/oiduna")
        logger.info("   uv run python -m oiduna_api.main")
        logger.info("4. クライアントから以下でアクセスできます:")
        for hostname in self.local_hostnames:
            logger.info(f"   curl http://{hostname}:57122/health")

    def teardown(self):
        """設定のロールバック"""
        logger.info("=== Oiduna Network Setup ロールバック開始 ===")

        # ホットスポット削除（wifi_only, bridgeモード）
        if self.mode in ["wifi_only", "bridge"]:
            logger.info("ホットスポットを削除中...")
            try:
                subprocess.run(
                    ["nmcli", "connection", "delete", "Hotspot"],
                    capture_output=True,
                )
                logger.info("✓ ホットスポットを削除しました")
            except Exception as e:
                logger.warning(f"ホットスポット削除に失敗（既に削除済みの可能性）: {e}")

        # ブリッジ削除（bridgeモード）
        if self.mode == "bridge":
            logger.info(f"ブリッジ {self.bridge_interface} を削除中...")
            try:
                subprocess.run(
                    ["ip", "link", "delete", self.bridge_interface],
                    capture_output=True,
                )
                logger.info(f"✓ ブリッジ {self.bridge_interface} を削除しました")
            except Exception as e:
                logger.warning(f"ブリッジ削除に失敗（既に削除済みの可能性）: {e}")

        # Ethernet LAN設定削除（ethernet_onlyモード）
        if self.mode == "ethernet_only":
            logger.info(f"Ethernet LAN ({self.ethernet_interface}) 設定を削除中...")
            try:
                subprocess.run(
                    ["ip", "addr", "flush", "dev", self.ethernet_interface],
                    capture_output=True,
                )
                logger.info(f"✓ {self.ethernet_interface} の設定を削除しました")
            except Exception as e:
                logger.warning(f"Ethernet LAN設定削除に失敗: {e}")

        # ローカルDNS設定削除
        logger.info("ローカルDNS設定を削除中...")
        dnsmasq_conf = Path("/etc/NetworkManager/dnsmasq-shared.d/oiduna-local-dns.conf")
        if dnsmasq_conf.exists():
            dnsmasq_conf.unlink()
            logger.info("✓ ローカルDNS設定を削除しました")

        # NetworkManager再起動
        subprocess.run(
            ["systemctl", "restart", "NetworkManager"],
            capture_output=True,
        )
        logger.info("✓ NetworkManagerを再起動しました")

        # NAT設定削除
        logger.info("NAT設定を削除中...")
        try:
            subprocess.run(
                ["iptables", "-t", "nat", "-F"],
                capture_output=True,
            )
            subprocess.run(
                ["iptables", "-F", "FORWARD"],
                capture_output=True,
            )
            logger.info("✓ NAT設定を削除しました")
        except Exception as e:
            logger.warning(f"NAT設定削除に失敗（既に削除済みの可能性）: {e}")

        logger.info("=== Oiduna Network Setup ロールバック完了 ===")
        logger.info("注意: IPフォワーディング設定（/etc/sysctl.conf）は手動で削除してください")


def load_config(config_path: Path) -> dict[str, Any]:
    """設定ファイル読み込み"""
    if not config_path.exists():
        logger.error(f"設定ファイルが見つかりません: {config_path}")
        sys.exit(1)

    try:
        with config_path.open("r") as f:
            config = yaml.safe_load(f)
        return config
    except Exception as e:
        logger.error(f"設定ファイルの読み込みに失敗しました: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Oiduna Network Setup Script - Ubuntu PCをWi-Fiアクセスポイント/LAN化",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).parent / "network_config.yaml",
        help="設定ファイルのパス（デフォルト: scripts/network_config.yaml）",
    )
    parser.add_argument(
        "--teardown",
        action="store_true",
        help="設定をロールバックする（元に戻す）",
    )

    args = parser.parse_args()

    # Teardownモード
    if args.teardown:
        # 設定ファイルから現在のモードを読み込んでロールバック
        if args.config.exists():
            config = load_config(args.config)
        else:
            # デフォルト設定でロールバック
            config = {
                "mode": "wifi_only",
                "upstream_interface": "eth0",
                "wifi_interface": "wlan0",
                "ethernet_interface": "eth1",
            }
        setup = NetworkSetup(config)
        setup.check_root()
        setup.teardown()
        return

    # セットアップモード
    config = load_config(args.config)

    # バリデーション
    mode = config.get("mode", "wifi_only")
    if mode in ["wifi_only", "bridge"]:
        if not config.get("password"):
            logger.error("設定ファイルにパスワードが設定されていません")
            sys.exit(1)

        if len(config["password"]) < 8:
            logger.error("パスワードは8文字以上にしてください")
            sys.exit(1)

    setup = NetworkSetup(config)
    setup.setup()


if __name__ == "__main__":
    main()
