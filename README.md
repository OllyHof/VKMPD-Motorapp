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

De app scant aanwezige COM-poorten op het Modbus-apparaat. De scan leest alleen
registers en stuurt geen bewegingscommando's. Hij probeert 9600 baud met even en geen
parity, plus 19200 en 115200 baud, met 8 databits en 1 stopbit. Als er geen apparaat
wordt gevonden, controleer de A/B-bedrading, voeding, driverinstelling en slave-ID.
Sluit het meegeleverde configuratieprogramma en andere seriële monitoren eerst af:
Windows laat normaal maar één programma tegelijk dezelfde COM-poort openen.

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

Na verbinden ververst de app de positie standaard elke 500 ms. Je kunt automatisch
verversen uitzetten of de interval instellen tussen 100 en 5000 ms. De keus tussen
graden, radialen en rotaties rekent doel, bereik, snelheid en versnelling automatisch om.

De snelheids- en versnellingsvelden zijn de maximumwaarden voor de gesloten-lus
positie-/snelheidsregeling. Snelheid is begrensd op de nominale 3000 rpm van deze
motor. De app start op 30°/s en 60°/s². Het softwarebereik start op ±360° en is
instelbaar tot maximaal ±3600°, ±20π radialen of ±10 rotaties. De app weigert een
doel buiten dat bereik. Dit is een softwaregrens, geen fysieke eindstop. Een
positiecommando kan de motor direct laten bewegen; houd de as vrij en begin met lage
limieten.

De app gebruikt registeradressen uit de [AQMD3605BLS-B2-handleiding](https://www.tinytronics.nl/product_files/006190_AQMD3605BLS-B2_UM_V0.90.zh-CN.en%20(1).pdf).
