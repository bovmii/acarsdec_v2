# Decodeur ACARS - acarsdec_v2.py (version francaise)

**Version 1.3**

*English version: voir `README.md`.*

Auteur : Boumediene Bahloul, stagiaire au laboratoire LASSENA (ETS Montreal).

---

## Ce que j'ai fait

J'ai ecrit un decodeur ACARS en Python, `acarsdec_v2.py`, independant d'acarsdec.

Je suis parti du decodeur de reference **acarsdec** (celui de Thierry Leconte,
fork f00b4r0). J'ai repris son algorithme : le **demodulateur MSK** (fichier
`msk.c`) et la **machine a etats de trame ACARS** (fichier `acars.c`), et je les
ai reecrits en Python. J'y ai ajoute un etage d'entree (accord du porteur,
detection d'enveloppe) et un mode d'ecoute continue sur RTL-SDR.

Pourquoi refaire le mien plutot qu'utiliser acarsdec directement : acarsdec s'est
revele penible a exploiter sur notre banc (dependances, formats de fichier
refuses, config RTL capricieuse). Mon decodeur tient dans **un seul fichier
Python**, tourne a l'identique sur **Linux et macOS**, et je controle
chaque etape, ce qui m'a permis de debugger l'emission ACARS du RFSoC.

Je l'ai valide de trois facons. Sur un enregistrement `test.wav` (2 messages,
CRC valide). Sur l'emission du **RFSoC** decodee en direct, ce qui prouve que la
modulation ACARS de notre carte est correcte. Et sur du **vrai trafic aerien** :
201 messages de 20 avions en deux heures, avec une antenne installee a cote de
l Ecole nationale d aerotechnique a Saint-Hubert, dont 94 % passent le CRC, le
plus lointain a 284 km. Cette capture est dans le depot.

---

## 1. Prerequis et installation

Il faut **Python 3** (n'importe quelle version 3.x recente, pas Python 2) avec
**numpy** et **scipy**, et les outils **rtl-sdr** (la commande `rtl_sdr`, utilisee
en ecoute continue).

### Installation automatique (recommande)

Le plus simple : **un script installe tout** (les dependances et la commande
`acarsdecv2`). Depuis le dossier `acarsdec_v2/` :

```bash
# macOS / Linux
./install.sh
```

C'est tout. Et si tu preferes faire les etapes toi-meme, pas de souci : la
methode manuelle ci-dessous marche tout aussi bien.

### Linux (Debian / Ubuntu)

```bash
sudo apt install rtl-sdr python3-numpy python3-scipy
```

Si le RTL est tenu par un autre service (ADS-B) ou le module noyau DVB :

```bash
sudo systemctl stop readsb 2>/dev/null
sudo rmmod dvb_usb_rtl28xxu rtl2832_sdr 2>/dev/null
```

### macOS

```bash
brew install librtlsdr
python3 -m pip install numpy scipy
export PATH="/opt/homebrew/bin:$PATH"
```

### Verifier que le RTL est vu

```bash
rtl_test
```

### Optionnel : en faire une commande systeme

Pour taper `acarsdecv2` depuis n'importe ou (sans `python3` ni `./`) :

```bash
chmod +x acarsdec_v2.py
# macOS (Homebrew deja dans le PATH)
ln -sf "$PWD/acarsdec_v2.py" /opt/homebrew/bin/acarsdecv2
# Linux
sudo ln -sf "$PWD/acarsdec_v2.py" /usr/local/bin/acarsdecv2
```

Ensuite, depuis n'importe quel dossier : `acarsdecv2 -f 131.525`.
(Volontairement pas `acarsdec` tout court : ce nom est celui du decodeur de
reference, et l'ecraser casserait une installation existante.)
(Sous zsh, faire `rehash` une fois, ou ouvrir un nouveau terminal.)

---

## 2. Utilisation

> **Tous les exemples ci-dessous utilisent `acarsdecv2`**, la commande installee
> par `./install.sh`. **Si tu n'as pas lance l'installeur**, remplace partout
> `acarsdecv2` par `python3 acarsdec_v2.py`, depuis le dossier `acarsdec_v2/`.
> Les deux font exactement la meme chose.

Aide en francais : `acarsdecv2 helpfr`.

### Ecoute continue sur le RTL (le mode principal)

```bash
acarsdecv2 -f 131.525 -g 30
```

(pas besoin de `--live` : donne une frequence avec `-f` et l'ecoute demarre ; la commande nue affiche l'aide.)
J'ecoute la frequence en permanence et j'affiche chaque message des qu'il passe.
`Ctrl+C` pour arreter. **Rien n'est enregistre par defaut** : ajoute `--log` si
tu veux garder une trace (voir la section Enregistrement).

Exemple de sortie :

```
--------------------------------------------------
2026-07-13 15:48:10  131.525 MHz  (L:+77.4 dB  err:0)
Mode : F   Label : 14   Id : .   NAK
Aircraft reg: LASSENA
Text: test
```

Plusieurs frequences a la fois (multi-canal, un seul RTL) :

```bash
acarsdecv2 -f 131.525 131.725 131.825
```

Format de sortie (`full` par defaut, ou `line`, ou `json`) :

```bash
acarsdecv2 -f 131.525 --fmt line
acarsdecv2 -f 131.525 --fmt json -i LASSENA1
```

### Decoder une capture IQ

```bash
rtl_sdr -f 131400000 -s 1024000 -g 30 -n 6000000 capture.iq
acarsdecv2 capture.iq --format u8 --fs 1024000
```

### Decoder un fichier WAV (audio deja demodule)

```bash
acarsdecv2 enregistrement.wav
```

### Toutes les options

| Option | Role | Defaut |
|--------|------|--------|
| `--live` | forcer l'ecoute live (deja le defaut sans fichier) | - |
| `-f, --freq <MHz> [MHz ...]` | frequence(s) d'ecoute, plusieurs possibles | 131.550 |
| `-g, --gain <dB>` | gain RTL (mode live) | 30 |
| `--ppm <n>` | correction de frequence du RTL en ppm | 0 |
| `--save <fichier>` | mode live : sauver aussi l'IQ brut recu | - |
| `--format {u8,c64}` | format d'une capture IQ | u8 |
| `--fs <S/s>` | sample rate d'une capture IQ | 1024000 |
| `--carrier <Hz>` | offset du porteur dans la capture (sinon auto) | auto |
| `--fmt {full,line,json}` | format de sortie | full |
| `-b, --labels <L1,L2>` | ne garder que ces labels (ex: H1,Q0) | tous |
| `-e, --skip-empty` | masquer les messages sans texte | - |
| `-A, --downlink-only` | garder seulement avion vers sol (approx.) | - |
| `-i, --station <id>` | identifiant station (affiche en full/json) | - |
| `-v, --verbose` | etat de reception periodique (mode live) | - |
| `-a, --analyse` | expliquer chaque message champ par champ (voir plus bas) | - |
| `--log [fichier]` | enregistrer les messages decodes (voir Enregistrement) | desactive |

En mode live, le sample rate du RTL est choisi automatiquement pour couvrir
toutes les frequences demandees.

### Enregistrer les messages

Rien n'est enregistre par defaut. Deux facons de garder une trace :

```bash
acarsdecv2 -f 131.550 --log                    # fichier horodate dans acarsdec_v2/
acarsdecv2 -f 131.550 --log ~/Bureau/toit.txt  # choisir le fichier et le dossier
```

`--log` seul cree `acars_AAAA-MM-JJ_HH-MM-SS.txt` **dans le dossier du script**,
peu importe d'ou tu lances la commande. Avec un chemin, tu choisis l'endroit.

`--log` n'enregistre que les **messages decodes**. Pour capturer **tout** ce qui
s'affiche a l'ecran (banniere, lignes `[rtl]`, erreurs), utilise `tee`, qui est
une commande **du shell** et non une option de cet outil :

```bash
acarsdecv2 -f 131.550 | tee sortie.txt        # ecran + fichier
acarsdecv2 -f 131.550 | tee -a sortie.txt     # ajoute au lieu d'ecraser
acarsdecv2 -f 131.550 2>&1 | tee sortie.txt   # capture aussi les erreurs
```

`tee` a besoin des **deux** : le tube `|` avant lui, et un **nom de fichier**
apres lui. Sans nom de fichier il n'enregistre rien, il recopie juste a l'ecran.
Et sans `-a`, il ecrase le fichier a chaque lancement.

### Expliquer un message champ par champ

```bash
acarsdecv2 -f 131.550 -g 40 --analyse      # en direct
acarsdecv2 enregistrement.wav --analyse    # sur un fichier
```

Chaque message decode est suivi d un tableau qui le lit : compagnie et numero de
vol, route, chapitre ATA, position avec sa distance et son cap depuis le
recepteur, station sol, heures UTC, et les abreviations du metier presentes dans
le texte libre.

```
2026-07-28 10:15:03  131.550 MHz  (L:+44.8 dB  err:0)
Aircraft reg: C-FDCA
Text: M68AAC0638MMSNG AC0638/28/28/YYZYSJ/1414Z/405/1/32-00 /213540 /...
+------------+-------------------------------------------------------------+
| Field      | Meaning                                                     |
+============+=============================================================+
| C-FDCA     | aircraft registration, Canada                               |
| AC0638     | Air Canada flight 638                                       |
| YYZYSJ     | Toronto-Pearson to Saint John                               |
| 32-00      | ATA chapter 32 = landing gear and brakes                    |
+------------+-------------------------------------------------------------+
```

Il faut `analyse_acars.py` a cote du script (section 7). Sans lui le decodeur
fonctionne toujours, il le signale simplement.

### Quelles frequences ecouter

| Zone | Canaux ACARS |
|------|--------------|
| Amerique du Nord (Montreal) | **131.550** (principale), 130.025, 130.450, 129.125 |
| Europe | 131.725, 131.525 |
| Banc de test RFSoC | celle reglee dans la GUI (131.525 ou 136.950) |

Plusieurs frequences a la fois seulement si elles sont proches (moins de ~2 MHz
d'ecart), sinon elles sortent de la bande echantillonnee par le RTL.

---

## 3. Comment ca marche

Un message ACARS est module en **AM-MSK** : les donnees (2400 bits/s) modulent
une sous-porteuse audio a 1800 Hz (tons 1200 et 2400 Hz), et cet audio module
en amplitude (AM) la porteuse radio VHF (~131 MHz). Le recepteur retrouve
l'audio par detection d'enveloppe, puis demodule le MSK.

Ma chaine de traitement :

```
RTL-SDR (IQ a la porteuse)
   |  1. accorder la porteuse a 0 Hz (bande de base)
   |  2. reechantillonner le complexe a 12000 Hz (rejette le reste du spectre)
   |  3. detection d'enveloppe : |signal|  (recupere l'audio AM)
   v
Audio 12000 Hz
   |  4. demodulation MSK (VCO 1800 Hz + filtre adapte + decision I/Q staggeree + PLL)
   v
Bits -> octets
   |  5. machine a etats : SYN SYN SOH ... texte ... ETX, puis CRC
   |  6. verification parite + CRC 16 bits
   v
Message decode (si le CRC est bon)
```

Les etapes 4, 5 et 6 sont mon portage fidele d'acarsdec (fork f00b4r0). Les
etapes 1, 2, 3 et le mode live sont ma partie.

---

## 4. Comprendre la sortie

```
2026-07-13 15:48:10  131.525 MHz  (L:+77.4 dB  err:0)
Mode : F   Label : 14   Id : .   NAK
Aircraft reg: LASSENA
Text: test
```

- **Date / heure** : reception du message.
- **131.525 MHz** : la frequence (canal) qui a recu le message.
- **`L:`** : niveau du signal en dB (relatif). Trop faible = monter le gain,
  sature = le baisser.
- **`err:`** : erreurs de parite (0 = parfait).
- **`[CRC ERROR]`** apparait si le CRC ne tombe pas juste.
- **Mode / Label / Id / NAK-ACK / Aircraft reg / Text** : les champs ACARS.

Le meme bloc est ajoute au fichier de log si tu as utilise `--log`.

---

## 5. Depannage

- **Rien ne se decode** : verifier la frequence (`--freq`), le niveau (`L:` :
  monter/baisser `--gain`), et que le RTL recoit bien a cette frequence (les
  vieux dongles calent vers 131 MHz ; j'utilise un RTL-SDR Blog V4).
- **`rtl_sdr: command not found`** : rtl-sdr pas installe ou pas dans le PATH.
- **`usb_claim_interface error -6`** : un autre programme tient le RTL
  (`pkill acarsdec` ; `sudo systemctl stop readsb`).
- **`aucun message decode` sur un fichier** : verifier `--fs` et `--format`,
  ou forcer `--carrier <Hz>`.
- **Moins de messages au gain maximum** : plus de gain ne veut pas dire plus de
  sensibilite. Sur mon R820T le plancher de bruit passe de **+5 dB a gain 40 a
  +11 dB a 49.6**, et les avions lointains s y noient. Commencer vers 40 et ne
  monter que si les niveaux sont trop faibles.

### Le compteur n avance plus mais tout va bien

Les lignes `[rx] N message(s) | level ...` du `-v` sont le signe de vie. Tant
qu elles tombent toutes les 4 s, la chaine fonctionne, meme si le compteur ne
bouge pas : ca veut simplement dire que personne n emet. Des trous de plus d une
minute sont normaux sur un canal calme. Ce n est anormal que si **ces lignes
s arretent completement**.

### Si la RTL lache en cours de capture

La RTL peut cesser d alimenter le decodeur de deux facons : le processus
`rtl_sdr` se termine, ou il reste vivant sans plus rien envoyer (blocage USB).
Les deux terminaient la capture en silence. Elles sont maintenant detectees,
annoncees avec l heure **a l ecran et dans le `--log`**, et la RTL est relancee
automatiquement :

```
[rx] 2026-07-28 10:09:37  the RTL stopped sending data (rtl_sdr still running) after 214s. Restarting it (1/5), 34 message(s) so far.
[rx] 2026-07-28 10:09:39  RTL back, capture continues.
```

Abandon apres 5 echecs consecutifs, avec un code de retour 1 au lieu de 0 : une
capture de nuit qui a lache ne passe plus pour une capture terminee. Un flux qui
a tenu au moins 30 s compte comme un incident neuf, donc un simple hoquet USB ne
consomme pas le quota de relances.

### L affichage se fige mais le programme tourne toujours

Si la sortie s arrete net alors que le programme est clairement vivant (`Ctrl+C`
repond encore), c est le **terminal** qui bloque, pas le decodeur. Son tampon ne
fait que 1 Ko sur macOS : des qu il cesse d etre vide, et un `Ctrl+S` parti tout
seul en est la cause habituelle, le decodeur se bloque en moins d une minute.

Appuie sur **`Ctrl+Q`** : tout redefile d un coup et rien n est perdu. Pour
l eviter completement, garde le decodeur hors du terminal :

```bash
acarsdecv2 -f 131.550 -g 40 -v --log > ~/Bureau/sortie.txt 2>&1 &
tail -f ~/Bureau/sortie.txt
```

Seul le `tail` peut se figer, la capture continue.

---

## 6. Statut / validation

- Decode notre propre signal (`acars_tx.py`) : CRC valide.
- Decode un vrai enregistrement ACARS (`test.wav`) : 2 messages, CRC valide,
  la ou le vrai acarsdec refuse meme d'ouvrir le fichier (12500 Hz).
- Decode l'emission du **RFSoC** en direct via le RTL : CRC valide. Elle a aussi
  transporte sans alteration un message ATS de 73 caracteres, pas seulement une
  courte chaine de test.
- Decode du **vrai trafic aerien** a l'antenne : 201 messages, 20 avions,
  **94 % de CRC valides**, portee mesuree a **284 km**
  (`acquisition_2026-07-28.txt`).
- Recoupe sans faire confiance au CRC : deux comptes rendus de position d'un
  meme avion donnent une **vitesse sol de 848 a 933 km/h**, soit une vitesse de
  croisiere de jet. Un seul bit faux dans une position donnerait un chiffre
  absurde.
- Robustesse (test chaos monkey) : aucun plantage sur entrees adverses, et
  aucun faux positif (le bruit ne produit jamais de message a CRC valide).

---

## 7. L analyseur

`analyse_acars.py` fait la meme lecture sur les journaux enregistres, et ajoute
deux vues que le mode direct ne peut pas donner.

```bash
python3 analyse_acars.py mes_logs/*.txt             # chaque message, explique
python3 analyse_acars.py log.txt --summary          # seulement le bilan
python3 analyse_acars.py log.txt --positions        # positions, carte, vitesses
python3 analyse_acars.py log.txt --reg C-FDCA       # un seul avion
python3 analyse_acars.py log.txt --text BRAKE -n 5  # chercher, detailler 5
python3 analyse_acars.py log.txt --crc-ok           # ecarter les trames cassees
python3 analyse_acars.py log.txt --pos 45.50,-73.57 # autre point de reference
```

`--positions` liste chaque position recue avec sa distance et son cap, dessine
une carte en texte, et **reconstruit la vitesse sol et la route** a partir de
deux comptes rendus du meme avion. L ACARS ne transmet ni l une ni l autre, donc
une valeur plausible (un jet croise entre 800 et 950 km/h) est une preuve solide
que les deux positions ont ete decodees sans un seul bit faux.

### Capture d exemple

`acquisition_2026-07-28.txt` est une **vraie capture sur l air** : 201 messages
de 20 avions, enregistres sur 131.550 MHz a cote de l Ecole nationale
d aerotechnique a Saint-Hubert le 28 juillet 2026, sept sessions fusionnees en
un seul fichier. 94 % des trames passent le CRC, 14 portent une position, et
l avion le plus lointain etait a 284 km.

Les distances se comptent depuis un point de reference, donc indique le lieu
d enregistrement : `--pos 45.5175,-73.4169`. Sans cette option elles sont
calculees depuis le defaut, le campus de l ETS, a 12 km de la.

```bash
python3 analyse_acars.py acquisition_2026-07-28.txt --summary
python3 analyse_acars.py acquisition_2026-07-28.txt --positions
python3 analyse_acars.py acquisition_2026-07-28.txt --text BRAKE
```

La derniere commande fait ressortir un message de maintenance d Air Canada
signalant une panne du circuit de freinage en vol, avec la procedure QRH qui l a
resolue. Il est la pour qu on puisse essayer l analyseur sur du trafic reel sans
posseder de recepteur.

### Les tables de reference

`acars_data.csv` contient **31 361 aeroports, aerodromes, heliports et bases
d hydravions** et **6 087 compagnies**. Il a ete construit une fois a partir de
OurAirports (domaine public) et OpenFlights, et il est **lu sur le disque
uniquement : l analyseur ne touche jamais au reseau**. Sans ce fichier il
retombe sur des tables integrees plus petites et fonctionne quand meme.

### Ce qu il refuse de faire

Il n affiche que ce qu il identifie vraiment. Beaucoup de labels ACARS sont
propres a chaque compagnie, donc il ecrit "airline defined" plutot que d inventer
un sens, et il ne revendique jamais de lieu pour une station sol.

La detection est volontairement prudente, parce qu une table complete fait
ressembler des mots anglais a des routes : `WEIGHT` se coupe en WEI + GHT,
`RUNWAY` en RUN + WAY, et `SYS` dans "BRAKE SYS 2 FAULT" est un vrai code IATA
en Russie. Les codes d aeroport ne sont donc lus que dans des champs delimites
par des barres obliques, et un numero de vol exige quatre chiffres et un code
compagnie connu. Les statistiques ignorent les trames rejetees par le CRC, car
un contenu corrompu produit des resultats plausibles mais faux.
