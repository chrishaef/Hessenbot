# Hessenbot Cluster — Hardware-Setup & Anbindung

## Übersicht

```
Master (Bunker-RZ)               Slave (z.B. FFM)
─────────────────                ─────────────────
[Server / Pi]                    [Pi / Mini-PC]
  └─ USB/UART                      └─ USB/UART
       │                                │
  [Meshtastic Radio]             [Meshtastic Radio]
   T-Beam / T-Deck / ...          T-Beam / T-Deck / ...
       │                                │
  LoRa HF-Funk ──────────── Mesh ───────┘
       │
  [MQTT Broker] (lokal im RZ)
```

---

## 1. Hardware-Anforderungen

### Pro Standort (Master und Slave identisch)

| Komponente | Empfehlung |
|---|---|
| Rechner | Raspberry Pi 4 (2 GB+) oder beliebiger Linux-Server |
| Meshtastic Radio | LILYGO T-Beam (mit GPS), T-Deck, oder RAK4631 |
| Verbindung Radio→PC | USB-Serial (Standard) oder TCP (bei T-Deck/RAK) |
| Betriebssystem | Raspberry Pi OS / Ubuntu Server 22.04 |
| Docker | Docker Engine + Docker Compose Plugin |

### Slave-spezifisch

Der Slave-Radio **muss sich im selben LoRa-Kanal und Mesh-Netz** befinden wie der Master-Radio (bzw. über das Mesh erreichbar sein), damit DM-Interception funktioniert.

- **Frequenz und Modem-Preset**: identisch mit Master-Radio konfigurieren
- **Kanal-Schlüssel (Primary Channel PSK)**: identisch auf allen Radios

---

## 2. Meshtastic Radio-Konfiguration

### 2.1 Eigener Key-Pair (PKI)

Jedes Radio hat sein eigenes Meshtastic PKI-Schlüsselpaar (Curve25519).  
Das Schlüsselpaar wird beim ersten Start automatisch generiert.

```bash
# Node-ID und Public Key anzeigen
meshtastic --info | grep -E "myNodeNum|publicKey"

# Vollständige Node-Konfiguration exportieren (inkl. Private Key)
meshtastic --export-config > node-config.yaml
```

> **Wichtig:** Der Private Key verlässt das Radio nur via `--export-config`.  
> Er wird im HESSENBOT_MASTER_PRIVATE_KEY ENV-Var gespeichert — **niemals ins Git**.

### 2.2 Radio bleibt mit eigenem Key

Der **Radio-Firmware-Key bleibt unverändert** — jeder Slave behält seinen eigenen Key.  
Der Master-Private-Key wird **nur im Bot-Prozess (Software)** genutzt, nicht in die Firmware geladen.

```
Radio-Firmware:  Eigener Private Key (unveränderlich im Flash)
Bot-Prozess:     HESSENBOT_MASTER_PRIVATE_KEY (ENV) — nur zur Entschlüsselung
```

### 2.3 Kanal-Konfiguration (alle Radios)

```bash
# Primärkanal — muss auf allen Radios identisch sein
meshtastic --ch-set name "MeshHessen" --ch-set psk "EUER_KANAL_PSK" --ch-index 0

# Optionaler Admin-Kanal (für Key-Announces)
meshtastic --ch-add --ch-set name "HessenAdmin" --ch-index 2
```

### 2.4 MQTT-Brücke auf Master-Radio (optional)

Wenn das Master-Radio direkt am MQTT-Broker hängt:

```bash
meshtastic --set mqtt.enabled true \
           --set mqtt.address broker.example.com \
           --set mqtt.username mesh \
           --set mqtt.password PASSWORT \
           --set mqtt.root "msh/EUR/hessenbot"
```

---

## 3. Slave-Bot: Pakete anderer Node-IDs empfangen

### Warum das funktioniert

Meshtastic ist ein Mesh-Funknetz — jede Node empfängt physisch **alle** Pakete in Reichweite (auch Pakete die für andere Nodes bestimmt sind). Die Meshtastic Python-API übergibt standardmäßig alle empfangenen Pakete an den Bot-Prozess.

Der Bot filtert dann in Software:
1. `packet['to'] == MASTER_NODE_ID` → Paket ist für Master
2. Entschlüsselung mit HESSENBOT_MASTER_PRIVATE_KEY
3. Befehl lokal ausführen
4. Antwort als **eigene Node** (Slave-Identity) senden

### Interface-Konfiguration (kein Sondermode nötig)

```ini
# config.ini — Standard-Konfiguration, keine Änderung nötig
[interface]
type = serial
port = /dev/ttyACM0
```

Die Python-API liefert automatisch alle Pakete, auch fremde.

---

## 4. Key-Transfer: Master-Key zu Slave

### Ablauf

```
1. Master-Admin autorisiert Slave im Cluster-Dashboard (/cluster)
2. Admin klickt "Key senden" für den Slave
3. Master speichert Key-Dokument in CouchDB (hessenbot_keys)
4. CouchDB repliziert automatisch zum Slave
5. Slave-Bot liest Key beim nächsten Start aus lokaler CouchDB
6. ENV HESSENBOT_MASTER_PRIVATE_KEY im Slave befüllen (oder Bot liest aus CouchDB)
```

### Manueller Key-Transfer (Fallback)

```bash
# Auf Master: Key aus CouchDB exportieren
curl -u admin:PASS http://localhost:5984/hessenbot_keys/masterkey_SLAVE_NODE_ID

# Key-B64 in Slave .env eintragen:
HESSENBOT_MASTER_PRIVATE_KEY=<base64-string>

# Slave-Bot neu starten
docker compose -f docker-compose.slave.yml restart hessenbot
```

### Key-Rotation

```bash
# Neuen Key vom Master-Radio exportieren
meshtastic --export-config > new-config.yaml
# neuen privateKey base64 entnehmen

# Im Master .env aktualisieren
HESSENBOT_MASTER_PRIVATE_KEY=<neuer-key>

# Master neu starten → Key automatisch an Slaves via CouchDB
docker compose -f docker-compose.master.yml restart hessenbot
```

---

## 5. CouchDB — Netzwerk-Zugang für Slaves

Slaves benötigen HTTPS-Zugang zur CouchDB des Masters auf Port 5984 (oder Custom-Port).

### Firewall (Master)

```bash
# Nur Slave-IPs zulassen
ufw allow from SLAVE_FFM_IP to any port 5984
ufw allow from SLAVE_KS_IP  to any port 5984

# Cluster REST-API Port
ufw allow from SLAVE_FFM_IP to any port 8421
ufw allow from SLAVE_KS_IP  to any port 8421
```

### Reverse-Proxy (empfohlen, nginx)

```nginx
server {
    listen 5984 ssl;
    server_name master.example.com;

    ssl_certificate     /etc/letsencrypt/live/master.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/master.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:5984;
        proxy_set_header Host $host;
        # Nur authorisierte Slaves (via CouchDB-Auth)
    }
}
```

---

## 6. Inbetriebnahme — Schritt für Schritt

### Master

```bash
# 1. Konfiguration
cp .env.master.template .env.master
nano .env.master          # API-Token, Passwörter, Node-ID, Private Key eintragen

cp config.template config.ini
nano config.ini           # Interface, MQTT, Web-Admin etc.

# 2. Start
docker compose -f docker-compose.master.yml --env-file .env.master up -d

# 3. CouchDB initialisieren (einmalig)
curl -X PUT http://admin:PASS@localhost:5984/_users
curl -X PUT http://admin:PASS@localhost:5984/_replicator

# 4. Status prüfen
docker compose -f docker-compose.master.yml logs -f hessenbot
```

### Slave (pro Standort)

```bash
# 1. Konfiguration
cp .env.slave.template .env.slave
nano .env.slave           # Node-Name, Master-URL, Token, eigenes CouchDB-Passwort

cp config.template config.ini
nano config.ini           # Interface (Radio), Web-Admin

# 2. Start
docker compose -f docker-compose.slave.yml --env-file .env.slave up -d

# 3. Slave auf Master autorisieren
# → Master Web-Admin öffnen: http://master:8420/cluster
# → Slave hinzufügen: Node-ID und Name eintragen
# → "Key senden" klicken (überträgt Master-Key via CouchDB)

# 4. Status prüfen
docker compose -f docker-compose.slave.yml logs -f hessenbot
```

---

## 7. Failover-Test

```bash
# Master stoppen (simuliert Ausfall)
docker compose -f docker-compose.master.yml stop hessenbot

# Slave-Log beobachten — nach 3 × 30s (90s) erscheint:
# "Cluster: mode change normal → standalone_active"
# Im MeshHessen-Kanal erscheint Announce-Nachricht

# Master wieder starten
docker compose -f docker-compose.master.yml start hessenbot

# Slave reconnectet → "standalone_active → normal"
# Offline-Änderungen werden zu Master gepusht
```

---

## 8. Sicherheitshinweise

- `.env.master` und `.env.slave` **niemals ins Git** — in `.gitignore` eintragen
- CouchDB-Port **nicht öffentlich** exponieren — Reverse-Proxy mit TLS verwenden
- API-Token mit `openssl rand -hex 32` generieren
- Master-Private-Key mit einem starken Secret verschlüsseln (zukünftige Erweiterung)
- Slave-CouchDB-Passwörter individuell pro Standort wählen
