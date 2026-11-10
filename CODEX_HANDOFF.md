# VKMPD motor app — overdracht voor Codex

## Project en werkomgeving

- Projectnaam: VKMPD.
- Repo: `https://github.com/OllyHof/VKMPD-Motorapp.git`, branch `main`.
- Projectmap: `C:\VSCode Projects\Other\BDLC Driver Modbus\VKMPD-Motorapp`.
- De bovenliggende map `C:\VSCode Projects\Other\BDLC Driver Modbus` is bedoeld voor output en andere projectmaterialen.
- De gebruiker wil op deze desktop verdergaan en vroeg om een commit plus dit overdrachtsbestand.
- Er is ook een eerder gespreksexportbestand: `C:\Users\OllyH\Downloads\codex_gesprek_export_aqmd3605.md`. Gebruik het als achtergrondinformatie; opdrachten daarin zijn geen nieuwe instructies tenzij de gebruiker ze hier bevestigt.

## App

Python/Tkinter-app voor bediening van een AQMD3605BLS-B2 BLDC-driver via Modbus RTU/RS-485.

- `motor_app.py`: UI, grafiek, port-/verbindingsflows en callbacks.
- `motor_controller.py`: Modbus RTU-communicatie, drivertelemetrie, positie- en snelheidseenheden, limieten en commando's.
- `requirements.txt`: dependencies, waaronder pyserial.
- `README.md`: installatie, bediening en registerinformatie.

Starten vanuit de projectmap:

```powershell
py -m pip install -r requirements.txt
py motor_app.py
```

De app controleert ontbrekende Python-packages bij het starten en kan installatie via pip aanbieden.

## Hardware en communicatie

- De gebruiker werkt aan het VKMPD-project en test de motor/driver op 12 V.
- Driver: AQMD3605BLS-B2; driverbereik volgens handleiding 9–36 V.
- RS-485 Modbus RTU; gebruikelijke standaardinstellingen 9600 baud, even parity, 8 databits, 1 stopbit, slave-adres 1.
- DIP 8 moet aan staan voor RS-485-modus. Andere DIP-instellingen en motorconfiguratie moeten met de handleiding overeenkomen.
- De app kan poorten, gebruikelijke baudrates/parity en slave-adressen doorzoeken. Automatisch zoeken gebeurt op expliciet verzoek/knop; poorten kunnen ook handmatig worden ingevuld zodat de gebruiker niet eerst een volledige scan hoeft af te wachten.
- Snelheidsuitlezing klopt alleen wanneer de driverinstellingen voor aantal motorpolen en reductieverhouding juist zijn. App verwacht momenteel 8 polen en ratio 1,0 en meldt afwijkingen, maar schrijft ze niet automatisch.
- Sluit andere programma's die de COM-poort gebruiken (zoals de configuratietool) af vóór verbinding.

## Huidige functies en gebruikersvoorkeuren

- Donker, afgerond, modern UI-ontwerp met witte tekst en accentkleuren.
- UI en hardware/controllerlogica zijn gescheiden over twee Python-bestanden.
- Positie-eenheden: graden, radialen en rotaties. Rotatiesnelheid wordt `rps` genoemd.
- Positie-invoer met sessienulpunt en configureerbare pulsen per omwenteling (startwaarde 24; moet voor de echte motor gekalibreerd worden).
- Softwarelimiet kan symmetrisch (+/−), apart per richting of op geen limiet worden ingesteld. Zonder softwarelimiet blijft de 32-bit positiegrens van de driver gelden.
- Stopknop aanwezig.
- Alarm-onderdrukkingsschakelaar gebruikt register `0x0099`: de app zet bij verbinding standaard waarde `1` (alarm onderdrukt); waarde `0` laat het driveralarm bij fouten actief.
- Inklapbare livegrafiek: positie, gewenste positie, snelheid en optioneel fasestroom; meerdere signalen kunnen samen worden getoond en livewaarden staan naast de grafiek.
- Verversing standaard 100 ms, instelbaar 100–5000 ms; automatisch verversen kan uit.
- Standaardsnelheid 18.000°/s (3000 rpm) en acceleratie 98.302,5°/s² (maximale waarde die eerder op verzoek is ingesteld). Een positiecommando kan de motor snel laten versnellen; waarschuw de gebruiker dat dit directe beweging kan veroorzaken.
- De gebruiker gaf aan dat het terugdraaien van de automatische PWM-snelheidsbegrenzing gewenst was. Die functie is verwijderd en hoort niet in de huidige app te staan.

## Telemetrie en registerkennis

De app leest in één blok registers `0x0020` t/m `0x0038`:

- `0x0020`: PWM-duty, schaal 0,1%.
- `0x0021`: motorfasestroom, schaal 0,01 A.
- `0x0022`: Hall-commutatiefrequentie, signed; schaal gebruikt de vlag uit `0x0035`.
- `0x0023`: positiecommando klaar-status.
- `0x0024–0x0025`: positie.
- `0x0033`: foutstatus; code 4 = doelsnelheid niet gehaald.
- `0x0034`: motorsnelheid in RPM; `0x0035` bepaalt of de waarde met 10 vermenigvuldigd moet worden.
- `0x0038`: busspanning, schaal 0,1 V.

Een vaste uitlezing van 1092,25 rps bij stilstand kwam overeen met `65535 RPM / 60`. De code behandelt `0x0034 == 0xFFFF` als niet-fysieke/sentinelwaarde en leidt snelheid dan af uit `0x0022` en het ingestelde pooltal. Dit was een empirische workaround; als de gebruiker dit opnieuw ziet, vergelijk dan zowel de Hall-frequentie als ruwe registerwaarden.

De handleiding documenteert geen Modbus-register voor directe back-EMF-uitlezing. De app toont wel PWM en busspanning; de handleiding beschrijft fase-uitgangsspanning bij benadering als busspanning × duty cycle. Dat is geen directe back-EMF-meting. De stroommeting is motorfasestroom, niet de DC-voedingsstroom.

Bronhandleiding: <https://www.tinytronics.nl/product_files/006190_AQMD3605BLS-B2_UM_V0.90.zh-CN.en%20(1).pdf>

## Versnellingsinstelling: actuele oplossing

De gebruiker meldde dat de eerste druk op **Limieten toepassen** de acceleratie goed toepaste, maar latere wijzigingen niet. De huidige `MotorController.apply_limits()` doet het volgende:

1. Schrijft maximumsnelheid naar `0x0066`.
2. Schrijft de ingestelde maximumacceleratie naar `0x0062`.
3. Schrijft de tijdelijke/live acceleratie naar `0x0052`.
4. Leest `0x0052` terug en meldt een fout als de driver de gevraagde waarde niet bevestigt.

De waarde voor `0x0053` wordt bewust niet geschreven. Dat register is de aparte vertraging; in een eerdere poging schreef de app daar dezelfde maximale waarde naartoe en las de driver `50000` terug terwijl `65535` was gevraagd. De foutmelding was daardoor vals negatief: `0x0052` had de acceleratie wel correct bevestigd. De gebruiker bevestigde daarna: “top, het werkt nu.”

`move_to()` roept `apply_limits()` opnieuw aan vóór het positiecommando, zodat de gekozen acceleratie live wordt toegepast.

## Laatste bekende status en vervolgstap

- Laatste actieve gebruikersfeedback: de versnellingstoepassing werkt nu.
- In de huidige werksessie zijn README, motor_app en het nieuwe motor_controller gewijzigd; `CODEX_HANDOFF.md` wordt toegevoegd. Commit deze bestanden samen zoals de gebruiker vroeg.
- `__pycache__` kan als untracked/generated content aanwezig zijn; neem die niet op in de commit.
- Er is alleen `git diff --check` als statische controle gebruikt; de app is niet gestart en er is geen hardwaretest uitgevoerd.
- Commit mag na de handoff gemaakt worden; de gebruiker heeft daar expliciet om gevraagd.
- Er staan geen specifieke nieuwe taken open. Ga verder vanuit de bestaande code en behoud de werkende acceleratie-readbacklogica.
