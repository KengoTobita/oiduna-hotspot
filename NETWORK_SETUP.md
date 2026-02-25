# Oiduna Hotspot - ネットワーク構成ガイド

**対象**: Oidunaサーバーをネットワーク経由で利用したいユーザー
**目的**: Ubuntu PCをWi-Fiアクセスポイント化し、ローカルDNSを提供する
**リポジトリ**: [oiduna-hotspot](https://github.com/yourusername/oiduna-hotspot)

---

## 目次

1. [概要](#概要)
2. [ネットワークモード](#ネットワークモード)
3. [ユースケース](#ユースケース)
4. [技術スタック](#技術スタック)
5. [ネットワーク構成](#ネットワーク構成)
6. [主要設定項目](#主要設定項目)
7. [セットアップ手順](#セットアップ手順)
8. [Pythonによる自動セットアップ](#pythonによる自動セットアップ)
9. [トラブルシューティング](#トラブルシューティング)
10. [セキュリティ考慮事項](#セキュリティ考慮事項)

---

## 概要

Oidunaサーバーを実行するUbuntu Desktop PCを**Wi-Fiアクセスポイント（ソフトウェアルーター）**として動作させ、接続クライアントに対して**ローカルDNS**を提供する構成です。これにより、以下が可能になります：

- MIDI機器を物理接続したOiduna PCに、LAN内の他のPCからアクセス
- SuperDirt/SupernovaなどのOSC受信ソフトをネットワーク経由で利用
- IPアドレスではなくホスト名（例: `oiduna.local`）でアクセス
- Distribution（MARS DSLなど）を別PCで実行し、Oiduna APIを呼び出し

---

## ネットワークモード

Oidunaは3つのネットワークモードをサポートしています。用途に応じて選択してください。

### モード1: Wi-Fi Only（デフォルト）

```
[クライアントA] ──┐
[クライアントB] ──┼── Wi-Fi (wlan0) ── [Ubuntu PC] ── [インターネット (eth0)]
[クライアントC] ──┘                        │
                                    Oiduna Server
```

- **用途**: Wi-Fi経由でのみクライアント接続
- **必要なインターフェース**: Wi-Fi (wlan0) + 上流インターネット (eth0)（任意）
- **設定**: `mode: "wifi_only"`

### モード2: Ethernet Only

```
[クライアントA] ──┐
[クライアントB] ──┼── Ethernet (eth1) ── [Ubuntu PC] ── [インターネット (eth0)]
[クライアントC] ──┘                          │
                                      Oiduna Server
```

- **用途**: 有線LAN経由でのみクライアント接続（Wi-Fi不使用）
- **必要なインターフェース**: Ethernet (eth1) + 上流インターネット (eth0)（任意）
- **設定**: `mode: "ethernet_only"`

### モード3: Bridge（Wi-Fi + Ethernet統合）

```
[クライアントA (Wi-Fi)] ──┐
[クライアントB (Ethernet)]─┼── [br0 ブリッジ] ── [Ubuntu PC] ── [インターネット (別IF)]
[クライアントC (Wi-Fi)] ───┘        │                │
                             wlan0 + eth1      Oiduna Server
```

- **用途**: Wi-FiとEthernetを同一LANとして統合（全クライアントが同一サブネット）
- **必要なインターフェース**: Wi-Fi (wlan0) + Ethernet (eth1) + 上流インターネット（別IF、任意）
- **設定**: `mode: "bridge"`
- **特徴**:
  - Wi-Fi経由とEthernet経由のクライアントが相互に通信可能
  - すべてのクライアントが同一サブネット（例: `192.168.4.0/24`）に所属
  - dnsmasqはbr0にバインド

**推奨モード**:
- ほとんどのユースケース: **Wi-Fi Only**
- 有線LANのみで使用: **Ethernet Only**
- Wi-FiとEthernetを混在させて使用: **Bridge**

---

## ユースケース

### 1. ライブコーディング環境の分離構成

```
┌─────────────────────────────────────┐
│ クライアントPC (Distribution)       │
│  - MARS DSL / TidalCycles          │
│  - コード編集・コンパイル           │
│  - HTTP経由でOidunaに送信           │
└──────────────┬──────────────────────┘
               │ Wi-Fi/Ethernet
               ↓
┌─────────────────────────────────────┐
│ Ubuntu PC (Oiduna Server)           │
│  - Wi-Fiアクセスポイント            │
│  - Oiduna API (HTTP)                │
│  - SuperDirt/Supernova              │
│  - MIDI機器接続                     │
└─────────────────────────────────────┘
         │                │
         ↓                ↓
    SuperDirt          MIDI機器
    (OSC受信)         (ハードウェア)
```

### 2. B2Bセッション・コラボレーション

複数のクライアントPCから同じOidunaサーバーにアクセスし、協調的にパターンを制御します。

### 3. モバイルコントロール

タブレットやスマートフォンからOiduna APIを呼び出し、パラメータをリアルタイム制御します。

---

## 技術スタック

| コンポーネント | 技術 | 用途 |
|---------------|------|------|
| OS | Ubuntu Desktop 24.04 LTS | Oidunaサーバー |
| アクセスポイント | `hostapd` または NetworkManager ホットスポット | Wi-Fi AP化 |
| DHCP/DNS | `dnsmasq` | IPアドレス配布＋ローカルDNS |
| NAT/ルーティング | `iptables` / `nftables` + カーネルIPフォワーディング | インターネット接続共有 |
| ブリッジ | `bridge-utils` または `iproute2` (`ip link`) | ブリッジモード時のインターフェース統合 |
| Python自動化 | `pyroute2` | Pythonからブリッジ操作 |
| インターネット上流 | 有線LAN (`eth0` / `enpXsX`) | 上流インターネット接続（任意） |

---

## ネットワーク構成

### Wi-Fi Onlyモード

```
[インターネット] ── [有線LAN (eth0)] ── [Ubuntu PC] ── [Wi-Fi AP (wlan0)] ── [クライアント端末群]
                                            │
                                     NAT + DHCP + DNS
```

- **Wi-Fiアダプタ（`wlan0`）**: APモードでホットスポット運用
- **有線LAN（`eth0`）**: 上流インターネット接続（必要な場合）
- **サブネット例**:
  - 手動構成時: `192.168.4.0/24`
  - NetworkManager使用時: `10.42.0.0/24`

### Ethernet Onlyモード

```
[インターネット] ── [有線LAN (eth0)] ── [Ubuntu PC] ── [Ethernet (eth1)] ── [クライアント端末群]
                                            │
                                     NAT + DHCP + DNS
```

- **Ethernetアダプタ（`eth1`）**: クライアント接続用
- **有線LAN（`eth0`）**: 上流インターネット接続（必要な場合）
- **サブネット**: `192.168.4.0/24`（設定で変更可能）

### Bridgeモード

```
[クライアントA (Wi-Fi)] ──┐
                          ├── [br0 ブリッジ] ── [Ubuntu PC] ── [インターネット]
[クライアントB (Ethernet)]┘        │              │
                            wlan0 + eth1   NAT + DHCP + DNS
```

- **ブリッジインターフェース（`br0`）**: wlan0とeth1を統合
- **Wi-Fiアダプタ（`wlan0`）**: APモードでホットスポット運用（br0に接続）
- **Ethernetアダプタ（`eth1`）**: クライアント接続用（br0に接続）
- **サブネット**: `192.168.4.0/24`（すべてのクライアントが同一サブネット）
- **dnsmasq**: br0にバインド

---

## 主要設定項目

### 1. IPフォワーディングの有効化

```bash
# 一時的に有効化
echo 1 | sudo tee /proc/sys/net/ipv4/ip_forward

# 永続化: /etc/sysctl.conf に追記
echo "net.ipv4.ip_forward=1" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

### 2. NAT（マスカレード）

```bash
# iptablesでNATを設定（eth0が上流インターフェース）
sudo iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
sudo iptables -A FORWARD -i wlan0 -o eth0 -j ACCEPT
sudo iptables -A FORWARD -i eth0 -o wlan0 -m state --state RELATED,ESTABLISHED -j ACCEPT

# 設定を永続化（iptables-persistent使用）
sudo apt install iptables-persistent
sudo netfilter-persistent save
```

### 3. dnsmasq設定（DHCP + ローカルDNS）

手動でhostapdを使用する場合は `/etc/dnsmasq.conf` を編集：

```conf
# Wi-Fiインターフェース
interface=wlan0

# DHCPレンジ
dhcp-range=192.168.4.10,192.168.4.100,24h

# DNSサーバーとして自身を通知
dhcp-option=6,192.168.4.1

# ローカルDNSレコード
address=/oiduna.local/192.168.4.1
address=/oiduna-server.local/192.168.4.1

# 上流DNSサーバー（インターネット接続がある場合）
server=8.8.8.8
server=8.8.4.4
```

### 4. NetworkManagerホットスポット使用時の代替パス

GUIホットスポットを利用する場合、dnsmasq設定は以下に配置：

```bash
# /etc/NetworkManager/dnsmasq-shared.d/local-dns.conf
sudo mkdir -p /etc/NetworkManager/dnsmasq-shared.d
sudo tee /etc/NetworkManager/dnsmasq-shared.d/local-dns.conf <<EOF
address=/oiduna.local/10.42.0.1
address=/oiduna-server.local/10.42.0.1
EOF

# NetworkManager再起動
sudo systemctl restart NetworkManager
```

### 5. Oiduna API設定

Oidunaをすべてのインターフェースでリッスンするように設定：

```bash
# .env ファイルまたは環境変数
API_HOST=0.0.0.0    # すべてのインターフェースでリッスン
API_PORT=57122

OSC_HOST=127.0.0.1  # SuperDirtはローカルホスト
OSC_PORT=57120
```

---

## セットアップ手順

### 前提条件

1. Wi-Fiアダプタが**APモード対応**であること

```bash
# APモード対応確認
iw list | grep -A 10 "Supported interface modes"
# 出力に "* AP" が含まれていること
```

2. 必要パッケージのインストール

```bash
# ホットスポットを手動構築する場合
sudo apt update
sudo apt install hostapd dnsmasq iptables-persistent

# NetworkManagerホットスポットを使う場合（推奨）
# NetworkManagerは既にインストール済み
sudo apt install dnsmasq-base
```

### 方法1: NetworkManagerホットスポット（推奨）

**最も簡単な方法です。**

1. **ホットスポットを作成**

```bash
# GUIから: Settings → Wi-Fi → Turn On Wi-Fi Hotspot
# またはCLIから:
nmcli device wifi hotspot ssid "Oiduna-Network" password "your-password"
```

2. **ローカルDNS設定を追加**

```bash
sudo mkdir -p /etc/NetworkManager/dnsmasq-shared.d
sudo tee /etc/NetworkManager/dnsmasq-shared.d/local-dns.conf <<EOF
address=/oiduna.local/10.42.0.1
address=/oiduna-server.local/10.42.0.1
EOF
```

3. **NetworkManager再起動**

```bash
sudo systemctl restart NetworkManager
```

4. **Oiduna起動**

```bash
cd /path/to/oiduna

# .envファイルを編集
cat > .env <<EOF
API_HOST=0.0.0.0
API_PORT=57122
OSC_HOST=127.0.0.1
OSC_PORT=57120
EOF

# SuperDirt起動
sclang  # SuperColliderを起動してSuperDirt.start

# Oiduna API起動
uv run python -m oiduna_api.main
```

5. **クライアントから接続**

```bash
# クライアントPCからWi-Fi "Oiduna-Network" に接続

# 疎通確認
ping oiduna.local

# Oiduna APIにアクセス
curl http://oiduna.local:57122/health
# → {"status": "ok"}
```

### 方法2: hostapd + dnsmasq（手動構築）

より詳細な制御が必要な場合は、hostapdとdnsmasqを手動で設定します。

1. **hostapd設定**

```bash
sudo tee /etc/hostapd/hostapd.conf <<EOF
interface=wlan0
driver=nl80211
ssid=Oiduna-Network
hw_mode=g
channel=7
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=your-password
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
EOF
```

2. **dnsmasq設定**

上記「主要設定項目」の3を参照。

3. **サービス起動**

```bash
sudo systemctl unmask hostapd
sudo systemctl enable hostapd
sudo systemctl start hostapd

sudo systemctl enable dnsmasq
sudo systemctl start dnsmasq
```

4. **NAT設定**

上記「主要設定項目」の2を参照。

---

## Pythonによる自動セットアップ

上記のネットワーク構成をPythonスクリプトで自動化します。

### スクリプトの場所

```
oiduna-hotspot/
    setup_network.py      # ネットワーク自動セットアップスクリプト
    network_config.yaml   # ネットワーク設定ファイル
    examples/             # 設定例
```

### 使用方法

#### 共通手順

```bash
cd /path/to/oiduna-hotspot

# 必要な依存関係をインストール
uv sync
# または
pip install -r requirements.txt

# インターフェース名を確認
ip link
# 出力例:
# 1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 ...
# 2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> ...  ← 上流インターネット
# 3: wlan0: <BROADCAST,MULTICAST> ...              ← Wi-Fi AP用
# 4: eth1: <BROADCAST,MULTICAST> ...               ← クライアント接続用（Ethernet Only / Bridgeモード）
```

#### モード1: Wi-Fi Only（推奨）

```bash
# ネットワーク設定ファイルを編集
cat > network_config.yaml <<EOF
mode: "wifi_only"
ssid: "Oiduna-Network"
password: "your-password"
subnet: "10.42.0.0/24"
gateway_ip: "10.42.0.1"
local_hostnames:
  - "oiduna.local"
  - "oiduna-server.local"
upstream_interface: "eth0"  # インターネット接続用
wifi_interface: "wlan0"     # Wi-Fi AP用
EOF

# スクリプト実行（root権限が必要）
sudo python setup_network.py --config network_config.yaml

# ロールバック（元に戻す）
sudo python setup_network.py --teardown
```

#### モード2: Ethernet Only

```bash
# ネットワーク設定ファイルを編集
cat > network_config.yaml <<EOF
mode: "ethernet_only"
subnet: "192.168.4.0/24"
gateway_ip: "192.168.4.1"
local_hostnames:
  - "oiduna.local"
  - "oiduna-server.local"
upstream_interface: "eth0"     # インターネット接続用
ethernet_interface: "eth1"     # クライアント接続用
EOF

# スクリプト実行
sudo uv run python scripts/setup_network.py --config scripts/network_config.yaml

# ロールバック
sudo uv run python scripts/setup_network.py --teardown
```

#### モード3: Bridge（Wi-Fi + Ethernet統合）

```bash
# ネットワーク設定ファイルを編集
cat > network_config.yaml <<EOF
mode: "bridge"
ssid: "Oiduna-Network"
password: "your-password"
subnet: "192.168.4.0/24"
gateway_ip: "192.168.4.1"
local_hostnames:
  - "oiduna.local"
  - "oiduna-server.local"
upstream_interface: "eth0"     # インターネット接続用（任意、別IFが必要）
wifi_interface: "wlan0"        # Wi-Fi AP用（br0にブリッジ）
ethernet_interface: "eth1"     # クライアント接続用（br0にブリッジ）
EOF

# スクリプト実行
sudo uv run python scripts/setup_network.py --config scripts/network_config.yaml

# ロールバック
sudo uv run python scripts/setup_network.py --teardown
```

**注意**: Bridgeモードで上流インターネット接続が必要な場合、USBイーサネットアダプタなど**3つ目のネットワークインターフェース**が必要です。クローズドLANとして運用する場合は不要です。

### スクリプトの機能

#### 共通機能

1. **root権限チェック**: スクリプトがroot権限で実行されているか確認
2. **必要パッケージの確認と自動インストール**: NetworkManager、dnsmasq-base、bridge-utils（bridgeモード時）
3. **IPフォワーディング有効化**: `sysctl` による設定 + `/etc/sysctl.conf` への永続化
4. **NAT設定**: `iptables` ルールの適用と永続化
5. **ローカルDNS設定**: dnsmasq設定ファイル生成（ホスト名・サブネット等をパラメータ化）
6. **サービス起動/再起動**: `systemctl` 経由で `dnsmasq`、`NetworkManager` を制御
7. **ステータス確認・ログ出力**: 各ステップの成否を確認し、エラー時は原因を出力
8. **ロールバック機能**: `--teardown` フラグで設定を元に戻す

#### モード別機能

**Wi-Fi Onlyモード**:
- Wi-FiアダプタのAPモード対応確認
- NetworkManagerホットスポット作成

**Ethernet Onlyモード**:
- Ethernetインターフェースへのスタティック IP設定

**Bridgeモード**:
- Wi-FiアダプタのAPモード対応確認
- ブリッジインターフェース（br0）作成（pyroute2またはipコマンド使用）
- wlan0とeth1をbr0にブリッジ接続
- br0へのIPアドレス割り当て

詳細は [setup_network.py](./setup_network.py) を参照してください。

---

## トラブルシューティング

### Wi-FiアダプタがAPモードに対応していない

```bash
# APモード対応確認
iw list | grep -A 10 "Supported interface modes"

# "* AP" が含まれていない場合、別のWi-Fiアダプタが必要
# 推奨: Atheros AR9271, Realtek RTL8812AU などのチップセット
```

### ホットスポットが起動しない

```bash
# NetworkManagerのステータス確認
sudo systemctl status NetworkManager

# dnsmasqのログ確認
sudo journalctl -u dnsmasq -f

# hostapdのログ確認（手動構築の場合）
sudo journalctl -u hostapd -f
```

### クライアントがDHCPでIPアドレスを取得できない

```bash
# dnsmasq設定確認
sudo cat /etc/dnsmasq.conf
# または
sudo cat /etc/NetworkManager/dnsmasq-shared.d/local-dns.conf

# dnsmasq再起動
sudo systemctl restart dnsmasq
# または
sudo systemctl restart NetworkManager
```

### ローカルDNSが機能しない

```bash
# クライアント側でDNS設定確認
cat /etc/resolv.conf
# nameserver 192.168.4.1 または 10.42.0.1 が含まれていること

# サーバー側でdnsmasqログ確認
sudo journalctl -u dnsmasq -f

# クライアント側でDNSクエリテスト
nslookup oiduna.local
# または
dig oiduna.local
```

### `.local` ドメインがmDNS（Avahi）と競合する

`.local` ドメインはmDNS（Zeroconf/Bonjour）で予約されているため、Avahiと競合する可能性があります。

**対処法1**: `.lan` ドメインを使用

```bash
# /etc/NetworkManager/dnsmasq-shared.d/local-dns.conf
address=/oiduna.lan/10.42.0.1
```

**対処法2**: Avahiを無効化（mDNSが不要な場合）

```bash
sudo systemctl disable avahi-daemon
sudo systemctl stop avahi-daemon
```

### Oiduna APIにアクセスできない

```bash
# サーバー側でOiduna APIが起動しているか確認
curl http://localhost:57122/health

# ファイアウォール設定確認
sudo ufw status

# ポート57122を開放（必要な場合）
sudo ufw allow 57122/tcp

# API_HOSTが0.0.0.0に設定されているか確認
cat .env | grep API_HOST
```

### ブリッジが作成できない（Bridgeモード）

```bash
# ブリッジの状態確認
ip link show br0

# ブリッジが存在しない場合、手動で作成
sudo ip link add br0 type bridge
sudo ip link set wlan0 master br0
sudo ip link set eth1 master br0
sudo ip link set br0 up

# ブリッジのメンバー確認
bridge link
```

### Wi-FiドライバがBridgeモードに対応していない

一部のWi-Fiドライバは、APモードとブリッジモードの同時使用に対応していません。

**症状**:
- `ip link set wlan0 master br0` でエラー
- `Operation not supported` エラー

**対処法1**: Wi-Fi Onlyモードを使用（ブリッジを諦める）

```yaml
mode: "wifi_only"
```

**対処法2**: 別のWi-Fiアダプタを使用

ブリッジモード対応のWi-Fiアダプタ（Atheros AR9271など）を使用してください。

### Ethernetクライアントが接続できない（Bridgeモード）

```bash
# Ethernetインターフェースの状態確認
ip link show eth1

# Ethernetインターフェースが有効化されているか確認
sudo ip link set eth1 up

# ブリッジメンバー確認
bridge link | grep eth1

# DHCPサーバーがbr0でリッスンしているか確認
sudo journalctl -u dnsmasq | grep br0
```

---

## セキュリティ考慮事項

### 1. Wi-Fiパスワード強度

強力なパスワードを使用してください（最低12文字、英数字記号混在）。

### 2. ファイアウォール設定

必要なポートのみを開放してください。

```bash
# UFWでファイアウォール設定
sudo ufw enable
sudo ufw allow 57122/tcp  # Oiduna API
sudo ufw allow 57120/udp  # SuperDirt OSC (必要な場合のみ)
```

### 3. HTTPS化（将来的な推奨事項）

本番環境やインターネット経由でアクセスする場合は、HTTPS化を検討してください。

- Nginx/Caddyをリバースプロキシとして使用
- Let's EncryptでSSL証明書を取得

### 4. 認証・認可

現在のOiduna APIには認証機能がありません。将来的には以下を検討してください。

- API Key認証
- OAuth 2.0 / JWT
- IP制限

---

## 関連ドキュメント

- [README.md](../README.md) - Oidunaの概要とクイックスタート
- [API_REFERENCE.md](API_REFERENCE.md) - HTTP APIエンドポイント全仕様
- [DISTRIBUTION_GUIDE.md](DISTRIBUTION_GUIDE.md) - Distribution（DSL）開発ガイド
- [ARCHITECTURE.md](ARCHITECTURE.md) - Oidunaのアーキテクチャと設計判断

---

## 参考リンク

- [Ubuntu NetworkManager Hotspot Documentation](https://help.ubuntu.com/community/WifiDocs/ShareAnInternetConnection)
- [hostapd Documentation](https://w1.fi/hostapd/)
- [dnsmasq Documentation](https://thekelleys.org.uk/dnsmasq/doc.html)
- [iptables Tutorial](https://www.netfilter.org/documentation/HOWTO/NAT-HOWTO.html)

---

**Last Updated**: 2026-02-24
**Version**: 1.0.0
