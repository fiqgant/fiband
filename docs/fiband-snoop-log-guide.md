# Guide: capturing Android's HCI snoop log (QWatch Pro)

Goal: record the Bluetooth commands that QWatch Pro exchanges with the band
while it syncs the history, to derive the sleep / historical BP / historical SpO2 /
HRV / stress commands (and to find out how many days the band keeps in memory).

## A. On the Android phone — enable logging

1. **Developer options**: Settings → About phone → tap "Build number" 7 times.
2. Go back to Settings → System → **Developer options**.
3. Enable **"USB debugging"**.
4. Enable **"Bluetooth HCI snoop log"**.
   - If it asks for a level, choose **"Enabled"** or **"Full"** (not "Filtered").
5. **Turn Bluetooth off and on again** (so a clean log starts).

## B. Reproduce a full sync

1. Open **QWatch Pro** and make sure it's connected to the band.
2. Force a **sync** (usually by pulling down the main screen).
3. **Open every history chart**, one by one, to force the app to download them:
   - Heart rate (day and week views)
   - **Sleep**
   - **Oxygenation (SpO2)** — history
   - **Blood pressure** — history
   - **HRV**
   - **Stress**
4. (Optional) Start a **manual BP and SpO2 measurement** from the app.
5. Note the time: needed to find the packets in the log.

## C. Download the log to the Mac (via adb)

On the Mac, once, install the Android tools:

```bash
brew install android-platform-tools
```

Plug the **phone into the Mac via USB**, unlock the screen and authorize USB
debugging when the phone asks. Then:

```bash
# verify the phone is seen
adb devices

# reliable method: bug report (contains the btsnoop)
adb bugreport ~/Downloads/band/bugreport.zip
```

Alternatively, on some phones the file is directly accessible:

```bash
adb pull /sdcard/btsnoop_hci.log ~/Downloads/band/
# or
adb pull /data/misc/bluetooth/logs/btsnoop_hci.log ~/Downloads/band/
```

## D. Delivery

Put the file (`bugreport.zip` or `btsnoop_hci.log`) in the project folder
`~/Downloads/band/`. From there I analyze it: I extract the 16-byte frames
exchanged with the band and derive the exact history commands.

## Privacy notes
The bug report also contains other phone data. I analyze it only for the
band's packets and there's no need to share it with anyone else.