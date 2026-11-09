# VKMPD · motorbediening voor AQMD3605BLS-B2

## Installeren en starten

1. Installeer Python 3.10 of nieuwer.
2. Open PowerShell in deze map.
3. Voer uit:

   ```powershell
   py -m pip install -r requirements.txt
   py motor_app.py
   ```

Bij het starten controleert de app zelf de pakketten uit `requirements.txt`. Ontbreekt
er een pakket, dan vraagt de app of pip het wil installeren met dezelfde Python-versie.
Daarvoor is een internetverbinding nodig. Als je installatie weigert, toont de app het
commando om de pakketten later handmatig te installeren.

## Projectbestanden

- `motor_app.py` bevat het scherm en de bedieningselementen.
- `motor_controller.py` bevat Modbus-communicatie, positieomrekening en de bewegingslimieten.
- `requirements.txt` bevat de externe Python-pakketten.

De app scant de aanwezige COM-poorten, probeert per poort de baudrate en zoekt daarna
het slave-adres. Bij een match verbindt de app automatisch. De scan leest alleen
registers en stuurt geen bewegingscommando's. Hij probeert 9600 baud met even en geen
parity, plus 19200 en 115200 baud, met 8 databits en 1 stopbit. Als er geen apparaat
wordt gevonden, controleer de A/B-bedrading, voeding, driverinstelling en slave-ID.
Sluit het meegeleverde configuratieprogramma en andere seriële monitoren eerst af:
Windows laat normaal maar één programma tegelijk dezelfde COM-poort openen.

Als je de COM-poort al weet, vul die dan direct in en kies baudrate, parity en
slave-adres. Klik op **Verbinden** om de volledige scan over te slaan. **Automatisch
zoeken** doorzoekt alle COM-poorten en verbindt zodra de driver is gevonden.

## Driver instellen

- Zet DIP-schakelaar 8 op **ON** voor RS485/Modbus-besturing.
- DIP 1–7 bepalen het slave-adres (1–128); de app probeert deze adressen.
- De driver gebruikt standaard 9600 baud, even parity en 1 stopbit. Baudrate is
  instelbaar in de driver en de scan probeert ook hogere gangbare snelheden.
- Stel de driver en motorstroom in volgens hun handleidingen. De motor is nominaal
  4,8 A; verander stroomlimieten alleen als je weet wat de motor en voeding aankunnen.

## Positie-eenheid en nulpunt

De driver levert de positie als pulstelling. Het aantal pulsen per omwenteling kan
afhangen van de motorconfiguratie. De app start met 24 als aannemelijke waarde voor
een 8-polige motor; kalibreer die waarde door de as precies één omwenteling te draaien
en de positiepulsverandering te meten. Daarna rekent de app pulsen om naar graden,
radialen of rotaties. **Stel dit in voordat je positiecommando's gebruikt.**

“Stel dit in als nul” maakt de huidige aspositie nul voor deze app-sessie. Dit schrijft
geen nulpunt naar het stuurprogramma en gaat verloren wanneer je de app afsluit.
Gebruik externe eindschakelaars of mechanische begrenzing waar nodig.

Na verbinden ververst de app de positie standaard elke 100 ms. Je kunt automatisch
verversen uitzetten of de interval instellen tussen 100 en 5000 ms. De keus tussen
graden, radialen en rotaties rekent doelpositie, snelheid en versnelling automatisch om.
De inklapbare livegrafiek kan positie, gewenste positie en snelheid tonen. De snelheid
komt uit de actuele drivertelemetrie. De geselecteerde signalen delen één y-schaal met
0 in het midden, zodat positieve en negatieve waarden zichtbaar zijn. De actuele
waarde van elke lijn staat rechts naast de grafiek. Rotatiesnelheid wordt aangeduid
als rps.

De positiekaart toont ook actuele motorsnelheid, motorfasestroom en driverstatus.
Snelheid komt uit register 0x0034 met de schaalvlag uit 0x0035; stroom komt uit
register 0x0021 (0,01 A per stap); foutstatus komt uit 0x0033. Daarnaast toont de app
busspanning (0x0038) en PWM-duty (0x0020). Er is geen afzonderlijk back-EMF-register
beschreven in de driverhandleiding. Voor de snelheidsuitlezing moeten
driverregisters 0x0073 en 0x0074 overeenkomen met 8 motorpolen en overbrengingsratio
1,0. De app leest deze instellingen en toont een melding als ze afwijken; de app
verandert ze niet automatisch.
De softwarematige positielimiet kan symmetrisch (±) of apart voor de positieve en
negatieve richting worden ingesteld, steeds rond het sessienulpunt. De limieten hebben
geen vaste bovengrens in de app. Het doel moet binnen die limiet blijven en passen in
het 32-bit positie-register van de driver.

De snelheids- en versnellingsvelden zijn de maximumwaarden voor de gesloten-lus
positie-/snelheidsregeling. Snelheid is begrensd op de nominale 3000 rpm van deze
motor. De app start op 18.000°/s (3000 rpm) en 98.302,5°/s²; dat is het maximum van
het acceleratieregister. Een doelcommando past deze waarden ook meteen toe. De motor
is gespecificeerd op 36 V; bij 12 V kan de voeding de werkelijke topsnelheid beperken.
Gebruik fysieke eindschakelaars of mechanische begrenzing waar nodig. Een
positiecommando kan de motor direct laten bewegen; houd de as vrij.

De app gebruikt registeradressen uit de [AQMD3605BLS-B2-handleiding](https://www.tinytronics.nl/product_files/006190_AQMD3605BLS-B2_UM_V0.90.zh-CN.en%20(1).pdf).
