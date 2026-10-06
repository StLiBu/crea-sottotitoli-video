# Crea sottotitoli video

Programma per Windows che trascrive l'audio di un video con Whisper e crea un MP4 con sottotitoli incorporati e un SRT modificabile. Non serve avere un file SRT iniziale. Audio e video vengono elaborati sul computer e l'originale non viene modificato.

## Avvio rapido

1. Installa Python 3.10 o successivo da [python.org](https://www.python.org/downloads/windows/) e attiva **Add python.exe to PATH**.
2. Scarica la repository con **Code → Download ZIP** ed estraila.
3. Fai doppio clic su `Avvia sottotitoli.cmd`. Al primo avvio prepara l'ambiente Python e installa le dipendenze.
4. Trascina il video nella finestra e premi Invio. Scegli cartella, lingua e dimensione dei sottotitoli.
5. Attendi il completamento. Al primo utilizzo viene scaricato il modello Whisper small (circa 500 MB); serve una connessione Internet.

Per usare le impostazioni predefinite, trascina il video direttamente sopra `Avvia sottotitoli.cmd`. Le istruzioni complete sono in [MANUALE D'USO.txt](MANUALE%20D'USO.txt).

## Risultati

Accanto al video (o nella cartella scelta) vengono creati `NOME_sottotitolato.mp4` e `NOME_sottotitoli.srt`. Il video contiene i sottotitoli nell'immagine e l'SRT resta modificabile. Il programma conserva audio e silenzi.

## Uso da terminale

Dopo il primo avvio:

```powershell
.venv\Scripts\python.exe video_subtitles.py "C:\percorso\lezione.mp4" --language it --font-size 9
```

Lingue: `it`, `en`, `es`, `fr`, `auto`. Per scegliere la cartella di destinazione aggiungi `--output-dir "C:\percorso\risultati"`.

## Accuratezza e privacy

Whisper può sbagliare nomi, sigle, formule e termini tecnici: controlla l'SRT prima di distribuire lezioni importanti. Video e audio restano sul computer; il modello viene scaricato da Hugging Face.

Il launcher automatico è per Windows. Il progetto è distribuito con licenza MIT (vedi `LICENSE`): chiunque può scaricarlo e usarlo, ma solo il proprietario o i collaboratori autorizzati possono caricare modifiche nella repository originale.
