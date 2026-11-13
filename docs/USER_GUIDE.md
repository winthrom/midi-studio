---
title: MIDI Studio User Guide
subtitle: For MIDI Studio 0.4.0
---

A program for turning a MIDI file into readable sheet music, listening to it, tidying it up and printing it.

## Contents

Click a line to jump to it.

- [1. What this program does](#what-this-program-does)
- [2. Getting the program](#getting-the-program)
    - [Windows 10 or 11 (64-bit)](#windows-10-or-11-64-bit)
    - [Linux (64-bit)](#linux-64-bit)
    - [macOS (Experimental)](#macos-experimental)
    - [Removing the program](#removing-the-program)
    - [Where the downloads are](#where-the-downloads-are)
- [3. Your first five minutes](#your-first-five-minutes)
- [4. The main window](#the-main-window)
    - [The row of buttons across the top](#the-row-of-buttons-across-the-top)
    - [The menus](#the-menus)
    - [The track list](#the-track-list)
- [5. Four ways of looking at the music](#four-ways-of-looking-at-the-music)
    - [Buttons at the top of the Score](#buttons-at-the-top-of-the-score)
    - [The editing tabs](#the-editing-tabs)
- [6. Setting the speed, time, key and title](#setting-the-speed-time-key-and-title)
    - [BPM, tempo change and listening speed](#bpm-tempo-change-and-listening-speed)
    - [When the measures are the wrong length](#when-the-measures-are-the-wrong-length)
    - [Quantize](#quantize)
- [7. Making a score easier to read](#making-a-score-easier-to-read)
    - [Hand-made files and performances](#hand-made-files-and-performances)
    - [Auto-Correct Score](#auto-correct-score)
    - [Separate Hands (piano, organ, accordion…)](#separate-hands-piano-organ-accordion)
    - [Fix Chords](#fix-chords)
    - [Fix Measures](#fix-measures)
    - [Remove Short Rests](#remove-short-rests)
    - [Rationalize Score](#rationalize-score)
    - [Compare with Original](#compare-with-original)
- [8. Playing: hands, fingers and marks](#playing-hands-fingers-and-marks)
    - [Easy to Play (hand over hand)](#easy-to-play-hand-over-hand)
    - [Fingering Numbers](#fingering-numbers)
    - [Suggest Marks](#suggest-marks)
    - [Marks on notes](#marks-on-notes)
    - [Soft Notes](#soft-notes)
- [9. Printing a score](#printing-a-score)
- [10. Something not working?](#something-not-working)
- [11. Telling me about a problem](#telling-me-about-a-problem)
- [12. Names, trademarks and what has been tested](#names-trademarks-and-what-has-been-tested)
- [Words used in this guide](#words-used-in-this-guide)
- [Index](#index)
- [Afterword: About MIDI files](#afterword-about-midi-files)

# 1. What this program does

A **Musical Instrument Digital Interface (MIDI) file** (ending in `.mid`) is not a recording. It is a list of instructions: "play this note, this loud, starting now, for this long." Most music players can play one. MIDI Studio reads that list and **draws it as sheet music**. You can then play it, watch a red line move across the score, zoom in, change the tempo, mute instruments, tidy the score, and print it.

You do not need to read music to use the program, but it helps. Words you may not know are explained in the [word list](#words-used-in-this-guide) at the end.

**Three rules to remember**

1. **Your original file is safe.** The program never changes your file unless you **Save** over it. When in doubt, use **File ▸ Save As…** and give the new version a new name.
2. **The recording is correct; the score is the program's reading of it.** If a score looks odd (a chord no hand could play, a note on the wrong staff, a strange rest), the music was almost certainly played correctly. The repair tools in this guide change how the *score is drawn*. They do not "fix" the person who played. The sound stays as recorded, except where a tool says plainly that it changes the sound (**Quantize**, **Soft Notes ▸ Raise**). Everything they do can be undone with **Edit ▸ Undo**.
3. **Suggestions can be wrong.** The program works out hands, fingers and marks from the notes alone. It can produce impossible results (hands or fingers that cannot be played). Check them by ear and eye with an expert such as a music teacher or performer (section 8).

# 2. Getting the program

## Windows 10 or 11 (64-bit)

**The easy way: the installer.** Download **MIDI-Studio-Setup.exe** and double-click it. It installs for only you (no administrator password is needed, because it is not shared with other users of your computer), adds MIDI Studio to your Start menu, and can put an icon on your desktop. To remove it later, use **Settings ▸ Apps** or the **Uninstall MIDI Studio** entry in the Start menu.

**Without installing: the zip file.** Download **MIDI-Studio-windows-x64.zip**. Right-click it, choose **Extract All…**, then click **Extract**. Open the new folder and double-click **MIDI-Studio.exe**. Do not run the program from inside the zip window; Windows lets you open a zip like a folder, but nothing works until it is extracted. Leave the `_internal` folder where it is.

**"Windows protected your PC".** Windows shows this because the program is free and not code-signed, so it says the publisher is unknown. Click the small faint words **More info**, then **Run anyway**. Windows should not ask again for that copy.

## Linux (64-bit)

Download **MIDI-Studio-x86_64.AppImage**. Make it runnable (right-click ▸ Properties ▸ *Allow executing as program*, or `chmod +x MIDI-Studio-x86_64.AppImage`) and double-click it. It carries its own copy of Python, the built-in synthesizer (FluidSynth) and a set of instrument sounds, so it makes sound without any setup. If you already have another synthesizer on your computer (a software one such as TiMidity, or a Musical Instrument Digital Interface (MIDI) keyboard or sound module), the program lists it under **Setup ▸ MIDI Output Device…** and you can choose it instead (section 10).

**Adding it to your application menu.** Download **install-linux.sh** from the same page and run `bash install-linux.sh` in the folder that holds both files. It copies the program to a folder called `Applications` in your home folder (no administrator password) and asks **"Add MIDI Studio to your application menu?"** Answer Enter for yes. To remove everything later, run `bash uninstall-linux.sh`; it also offers to remove a copy of LilyPond that MIDI Studio downloaded for you (it never touches one you installed yourself) and asks, with the standard answer No, whether to remove your saved settings.

**If the program will not start.** On recent Ubuntu and Kubuntu (24.04 and later) an AppImage may refuse to start until you install one small library: `sudo apt install libfuse2t64` (on older Ubuntu: `libfuse2`). The install script notices this and sets up the menu entry so that the program still starts, just a little slower.

**Running from the source code instead** is explained in the file `docs/LINUX_FROM_SOURCE.md` on the project page.

## macOS (Experimental)

**Please read this first.** The Mac versions are **experimental**. They have been built but not yet tested on every kind of Mac, and they are **not signed by Apple** (Apple charges a yearly fee for that, and this program is free). Everything in the program should work, but expect rough edges, and please tell me what you find (**Help ▸ Send a Problem Report…**, section 11).

**Testers wanted.** The Apple Silicon version is planned to be tested on a MacBook Pro with an M1 chip (Apple Silicon). The Intel version still needs a tester; if you have an Intel Mac, please get in touch at **winthrom@hotmail.com**.

**Which one do you need?** Click the Apple menu (top left), then **About This Mac**.

- If it says **Chip: Apple M1** (or M2, M3, M4…), download **MIDI-Studio-macos-apple-silicon.zip**.
- If it says **Processor: Intel**, download **MIDI-Studio-macos-intel.zip**. This is the one for older Macs.

**Installing.** Double-click the zip to unpack it. Drag **MIDI Studio** into your **Applications** folder. The first time, do **not** double-click it. **Right-click** (or hold Control and click) the program, choose **Open**, then click **Open** again in the box that appears. On a recent macOS you may instead see "MIDI Studio cannot be opened"; click **Done**, open **System Settings ▸ Privacy & Security**, scroll down to the message about MIDI Studio and click **Open Anyway**. After that it opens normally.

If macOS says the program is "damaged", open **Terminal** and type `xattr -dr com.apple.quarantine /Applications/MIDI\ Studio.app` and press Return. (This only removes the "downloaded from the internet" mark.)

**Printing** needs LilyPond: install it with `brew install lilypond` (section 9).

## Removing the program

- **Windows installer:** **Settings ▸ Apps**, or **Uninstall MIDI Studio** in the Start menu. If MIDI Studio had downloaded LilyPond for you, the uninstaller asks whether to remove it too (the standard answer is Yes), and then whether to remove your saved settings (the standard answer is No). A LilyPond that you installed or unpacked yourself is never touched.
- **Windows zip:** delete the folder you extracted. If MIDI Studio downloaded LilyPond, it is in `%LOCALAPPDATA%\MIDI-Studio\ly` (type that into the address bar of a File Explorer window); delete that folder too if you like.
- **Linux:** `bash uninstall-linux.sh`, or delete the AppImage file.
- **Mac:** drag **MIDI Studio** from Applications to the Trash.

## Where the downloads are

On the GitHub Releases page: `https://github.com/winthrom/midi-studio/releases/latest`. The newest version is always at the top. Download from this page, not from the "Actions" page (which needs a login and wraps files in an extra zip).

# 3. Your first five minutes

1. Start the program. A small window says **Starting MIDI Studio…** while the sounds load. On an older computer this can take about 12 seconds.
2. The first time, you may be asked to choose where sound comes from. Choose **FluidSynth (built in)**. You can change this later (section 10).
3. Click **File** (upper left), then **Open…** and choose a MIDI (`.mid`) file. The program remembers the folder you used last.
4. The music appears as a score. Each instrument gets its own line, called a **staff**. The name of each instrument is written above its staff at the left.
5. Click **▶ Play** (or press the **space bar**). You hear the music and a red line shows where you are. Click **⏹ Stop** to stop.

That is all you need to listen. Everything else in this guide is optional.

# 4. The main window

## The row of buttons across the top

| Button | What it does |
|---|---|
| **⏮** | Go back to the beginning. |
| **◀◀  ▶▶** | Jump back or forward by one measure. |
| **▶ Play** / **⏹ Stop** | Start (or pause) and stop the music. The space bar does the same as Play. |
| **⏺ Rec** | Record from a Musical Instrument Digital Interface (MIDI) keyboard connected to the computer. You do not need this just to listen. |
| **Click: OFF / ON** | Turns a metronome click on or off during playback. |
| **+ Track** | Adds a new empty instrument line. |
| **♫ Score**, **♬ Roll**, **📋 List**, **🎚 Mixer** | Open the four ways of looking at the music (section 5). |
| **BPM** | The speed in Beats Per Minute (BPM). A higher number is faster. |
| **Meas … Beat …** | Shows where you are in the piece. |
| **Sel … – … ▶ Sel** | Type a first and last measure, then click **▶ Sel** to play only that part. Useful for practising one passage. |

## The menus

**File**

- **New**, **Open…**, **Close Piece**: start fresh, open a file, or close the current one. Closing a piece also closes the correction windows that belonged to it.
- **Save**, **Save As…**: write the music to a MIDI file. **Save As…** suggests a new name ending in **-edited**, so your original keeps its own name. If you choose **Save** on a file you opened from disk, the program asks first: **Yes** = Save As (keeps the original safe), **No** = replace the original, **Cancel** = do nothing. Every saved file carries a small note, "Saved by MIDI Studio (version); sound as recorded", so you can tell it from an unedited file. If some notes were lengthened in the score only (for example by **Remove Short Rests**), the program asks whether to save the file **to match the score** or keep the **sound exactly as recorded** (the usual choice). Choosing "as recorded" means that if you reopen the file later, those score-only tidy-ups are not remembered; run them again.
- **Export ▸**: **MusicXML** (a format that notation programs such as MuseScore can open; for **Braille** music, see the note after this list), **Open in MuseScore (via MIDI)…** (if you have MuseScore installed), and **LilyPond (.ly)…**.
- **Print Score (via LilyPond)…**: for printing a high-quality score (section 9).

**Braille music.** MIDI Studio does not make Braille itself. A possible route is to export **MusicXML** and open it in a Braille-music tool, for example the Braille plugin of OpenSheetMusicDisplay (<https://github.com/opensheetmusicdisplay/opensheetmusicdisplay/blob/feat/braille/src/Plugins/Braille/UserGuide.md>). **This has not been tested with MIDI Studio's files yet.** If you read Braille music and can try it, please tell me what happened.
- **Close Program**.

**Edit**

- **Undo** / **Redo** (Ctrl+Z / Ctrl+Y): step back or forward through the changes you made, one at a time.
- **Editing tabs On/Off**: turns the Score's editing tabs on or off (section 5).
- **Hear selected notes ▸ On / Off**: when it is on (the usual setting), notes you select in the Score are sounded briefly so you can hear what you picked. It does nothing while the music is playing or recording, and it never changes the music.

**Tracks**

- **Add Track** / **Delete Track**.
- **Combine Tracks…**: merge several instrument lines into one.
- **Separate Channels…**: split one track that holds several instruments into one track each.

**Fix File**: repairs for a file as it was loaded, in the order you would usually use them (section 7). They change the written score only, except Quantize.

- **Auto-Correct Score…**: runs the safe repairs in one go and then shows what changed.
- **Separate Hands…**: for two-handed keyboard instruments (piano, organ, accordion…), sort the notes into a right-hand staff and a left-hand staff.
- **Remove Short Rests…**: close the tiny gaps between notes.
- **Fix Measures…**: find staves whose music runs past a barline, and fix them one measure at a time.
- **Fix Chords…**: find chords that no hand could play and choose what to do about them.
- **Rationalize Score…** (Ctrl+R).
- **Quantize… (changes the sound)** (Ctrl+Q).
- **Compare with Original…**: report what is different from the file as you opened it.

**Playing**: tools that make the music easier to play and read (section 8). Their results are suggestions.

- **Easy to Play (hand over hand)…**: find places where the melody and a held figure are in the wrong hands.
- **Fingering Numbers…**: show suggested fingers on the score. Off until you turn them on.
- **Suggest Marks…**: suggest staccato and accent marks from how the music was played.
- **Soft Notes…**: find notes played so softly they are probably accidents.

**Score**

- **Score Settings…** (Ctrl+G): where you set the title, composer, speed, time signature and the number of measures (section 6).
- **Key Signature…**
- **Quantization ▸**: the grid size.
- **Grace Cleanup ▸**: whether to delete extremely short notes. It starts **Off**, because it deletes notes.

**View**

- **Score View** (Ctrl+1), **Piano Roll** (Ctrl+2), **MIDI List** (Ctrl+3) and **Mixer**.
- **Listening speed ▸**: 50%, 60%, 70%, 80%, 90% or 100% (as written), or **Other speed…** to type any value in Score Settings. It changes only what you hear (section 6).

**Setup**

- **MIDI I/O Info**: shows (I/O means Input/Output) what the program found for sound output and for a connected keyboard.
- **MIDI Output Device…**: choose which "synthesizer" makes the sound, and its volume (section 10).

**Help**

- **User Guide (PDF)** opens this guide (Portable Document Format, PDF).
- **Where do I find…?** Type a word such as *speed*, *print*, *fingering* or *title* and it tells you which menu has it. Press **Enter**, or double-click a line, to open this User Guide at that topic. The topics it knows are the ones in the **Index** at the end of this guide. (In a web browser's PDF viewer it jumps to the section; another PDF program may open at the first page, and the Contents at the top of this guide will take you there.)
- **Send a Problem Report…** and **Tester Log**: see section 11.
- **Check for Updates…** looks on the project's GitHub page for a newer version and tells you; it never installs anything by itself. **Update check at startup ▸ On / Off** chooses whether the program looks once a day.
- **About…** shows the version number and credits. The same version appears in the title bar.

When a repair window or a question box opens, it always appears on top of the windows that were open before it, so it cannot be hidden behind them.

## The track list

The list of instruments is a panel that can be **docked** (fixed in the main window) or **floated** (pulled out into its own window). **Right-click an instrument** for a menu: open it in Score, Roll or List; **Rename**; **Delete**; **Mute/Unmute** (silence it); **Solo/Unsolo** (hear only this one); **Arm for Record**.

# 5. Four ways of looking at the music

- **Score (♫)**: ordinary sheet music, one staff per instrument. A two-handed keyboard instrument (piano, organ, accordion…) gets two staffs joined together (right hand on top, left hand below). This is the view most people use.
- **Piano Roll (♬)**: each note is a bar. Higher notes are higher on the screen; longer notes are longer bars. Easy to see exactly when each note starts and stops.
- **MIDI List (📋)**: a plain table of every note in the file, with its measure. For checking details.
- **Mixer (🎚)**: a volume control, a Mute and a Solo for each instrument, and a place to choose its instrument sound. If there are more instruments than fit, use the scroll bars at the bottom and right of the Mixer to reach them all (including the drums).

## Buttons at the top of the Score

| Button | What it does |
|---|---|
| **Zoom + / Zoom −** | Make the score bigger or smaller. |
| **Fit Width** | Squeeze or stretch the whole piece to the width of the window. |
| **Fit Width + / −** | Show one more or one fewer measure across the screen. |
| **Space + / Space −** | Move the staffs **further apart or closer together vertically**. Use it when high notes on one staff run into low notes on the staff above. |
| **Pedal marks** | A tick box. Shows or hides the "Ped." marks that come from the recorded sustain pedal. It only changes what the Score draws. |
| **Short rests** | A tick box. Normally the score hides rests shorter than a quarter note, so a performance does not look cluttered. Tick it to see the short rests too, down to a thirty-second note (section 7). |
| **Follow: Page / Follow: Smooth** | While playing, **Page** keeps the score still while the red line crosses a page of measures, then turns to the next page. **Smooth** slides the score under the red line. Page is the normal choice. |

**If your computer is slow:** Smooth movement needs a fast screen redraw. If the program finds your computer cannot keep up, it switches to Page by itself and shows a message saying so. Click **OK**; nothing is wrong. You can switch back to Smooth, and the program will not interrupt you again.

## The editing tabs

Under the buttons there is a row of tabs. When you open a piece, the editing tabs (**Note/Rest**, **Accidental**, **Dynamics**, **Articulation**) are **grayed out**, so a stray click cannot change anything. Click the **Select** tab (the last one) to turn editing on. You can turn it off again with **Turn editing off** on the Select tab, or by right-clicking the Select tab. Opening another file or closing the piece turns editing off again.

**How editing works.** Clicking a note, or dragging a box around several, only **selects** them (they turn blue). Nothing changes yet. Then pick a value on a tab, and press **Apply to Selection**. The button is gray until some notes are selected and a value is picked. If you have picked values on several tabs, they are all applied together as **one step**, and **Edit ▸ Undo** takes them all back. No tab starts with a value picked, and **Clear** on each tab un-picks it. Pressing **Esc** un-selects the notes.

- **Note/Rest**: pick a length, for example *quarter*, *dotted eighth*, *double-dotted quarter* or *32nd*. The selected notes take that length. A shorter note leaves a rest after it. If a longer note would run into the next note, the program asks what you want: **Cut off** (stop at the next note), **Hold** (keep the full length and let the other notes play over it, such as a held bass note under moving chords) or **Push later** (move the music after it later to make room). A note never runs past the end of its measure. Notes tied across a barline are skipped; the message says how many. This changes the sound, because the note really is longer or shorter.
- **Add notes by clicking** (on the Note/Rest tab, off at the start): with this ticked, clicking the staff adds a note, or, with **Rest** chosen, clicking a note turns it into a rest. Clicking a rest that is already drawn does nothing.
- **Accidental**: pick a sharp, flat or natural. The selected notes are changed to that.
- **Dynamics**: pick how loud (such as p, mf, f). It is placed at the first selected note.
- **Articulation**: pick a mark such as staccato (short and detached), tenuto or portato. Applying the same mark again to the same notes takes it off. The marks are explained in section 8 (**Marks on notes**).
- **Measures**: right-click any measure for **Insert**, **Delete** or **Cut**.
- **Move**: moves the selected notes earlier or later by a step you choose (from a 32nd note up to a whole note). Choose whether to move **these notes only**, **these and the rest of this staff**, or **these and the rest of every staff**. A rest is just the gap between notes, so the rests around the moved notes grow or shrink to match. Moving earlier stops at the previous note. **Remove Rest…** works on a rest you have selected (click it): it can **lengthen the note before it**, **close the gap in this staff** (the later notes move earlier), or **close the gap in every staff**. These really change the music, one **Undo** step each.
- **Select**: **Delete Selected** removes the selected notes. **Clear Selection** un-selects. **Move to Upper Staff** and **Move to Lower Staff** move them to the other hand's staff.

**Wrong staff?** Select the notes, right-click, and choose **Move … selected note(s) to upper staff** or **to lower staff**. Only the staff changes; the sound does not.

# 6. Setting the speed, time, key and title

Open **Score Settings ▸ Score Settings…** (Ctrl+G). The top part, **Global Calibration**, holds:

- **Title** and **Composer**: printed at the top of the score when you print (section 9) and saved inside the MIDI file. The title starts as the file's name; change it to anything you like.
- **Time Signature**: type it (for example 4/4 or 3/4) and click **Apply**.
- **Key Signature ▸ Change…**: choose the key (the sharps or flats at the start of each staff). The window also offers the program's guess.
- **BPM**: the Beats Per Minute number, plus **Apply**. See **BPM, tempo change and listening speed** below.
- **Tempo change (%)**: makes the whole piece play **faster or slower** in the saved file. See below.
- **Listening speed (%)**: plays it slower or faster for your ears only. See below.
- **Measures wanted**: see below.
- **Auto-detect BPM + Meter**: estimates the beat and the time signature.

Below that, **Clean up this measure** and **Clean up all measures** tidy how the notation is drawn, and **Bake** turns the cleaned-up look into the actual notes, so what you hear matches the score. Baking changes the notes, so use **Save As…** first.

## BPM, tempo change and listening speed

Three controls change the speed. They differ in what they touch.

- **BPM + Apply** sets the starting speed. **Typing the number that is already shown changes nothing.** A different number scales the whole speed line in proportion: if the file has tempo changes (a performance with give and take), they are kept and scaled together; if it has one steady tempo, that tempo changes. No note and no measure moves. One **Edit ▸ Undo** step.
- **Tempo change (%) + Apply** makes the piece play faster or slower **in the saved file**. 125 plays 25% faster; 80 plays 20% slower. Every tempo change is scaled together, and no note moves. One **Undo** step.
- **Listening speed (%) + Apply**, or **View ▸ Listening speed**, is **for your ears only**. It never changes the music, the saved file or the printed score. Choose a value from 25 to 200. While the music is playing, it carries on from the same place at the new speed; otherwise it applies the next time you press Play. The status bar shows "Listening speed" while it is not 100%. Use this to practise a passage slowly; use **Tempo change** only when you want the saved file to change.

## When the measures are the wrong length

A piece played slowly can show **two or three printed measures for one measure of the real score**. The speed (BPM) does not fix that, because the number of beats in a measure never changes. **Measures wanted** does. Type the number of measures the printed score has (for example 125) and look at the line under the box: it says how many measures you would get and how the notes will sit.

- **The sound does not change.** Only the barlines move.
- Notes are never moved. If the new measures cut a chord in half, run **Clean Up Measures** afterwards.
- **Quantize afterwards** (tick box, off by default) quantizes the notes right after the change. It is a second Undo step.
- The preview also names nearby measure counts where the notes stay exactly on the grid. That is arithmetic only: the right number of measures is the one your printed score has.

## Quantize

**Fix File ▸ Quantize… (Ctrl+Q)** pulls notes that were played slightly early or late onto an even beat grid. Choose the grid (quarter, eighth, sixteenth, thirty-second notes), how strongly to snap, and which measures. This **changes when notes play**. The window also has a **Grace note cleanup** that **deletes** notes shorter than the time you choose; it starts **Off**.

# 7. Making a score easier to read

A Musical Instrument Digital Interface (MIDI) file made by playing a piano is "human": the notes are a little early or late, one long list holds both hands, and a few chords look too wide for a hand. The tools in the **Fix File** menu get a readable score out of that. **Remember rule 2: the recording is correct.** These tools adjust the score, and each can be undone with **Edit ▸ Undo**.

## Hand-made files and performances

Some files are almost perfect scores already. A MIDI file **made by hand**, typed in or drawn note by note in notation software, has every note starting exactly where the one before ended. It needs very little help. A file recorded from **a person playing** is different. A player takes time to move between notes and chords: the finger lifts a moment before the next one lands, so each note stops a hair before the next one starts. On the score that gap is a **very short rest** between the notes, a "sliver". A performance can have over a thousand of them, and they make the score look busy and wrong even though the playing was fine.

You have three choices, and which is right is a matter of taste:

1. **Cover them up.** This is the normal setting. The score hides rests shorter than a quarter note, so it stays readable.
2. **Show them.** Tick **Short rests** at the top of the Score to see the gaps too, much nearer to how it was played.
3. **Remove them.** **Fix File ▸ Remove Short Rests…** (below) closes the gaps so they do not appear on the screen or in the print.

## Auto-Correct Score

**Fix File ▸ Auto-Correct Score…** runs the repairs that change only the written score, one after the other, so you do not have to open each window. It works on a copy, and **one Undo puts everything back**. The sound stays as recorded. The window offers three choices:

- **Separate hands (right and left).** Ticked when the file is not yet on two staffs; greyed out when it already has a right-hand and a left-hand part. This uses the standard stretch (12 semitones) and the most notes one hand can play (5). See **Separate Hands** below, and remember that the split can be wrong.
- **…and fix places where the split looks wrong (Follow the hands).** Off at the start. At places where a note is written far from its own staff (many ledger lines) while the other hand has nothing sounding there, it decides the hand by following where each hand has been, and may move the note to the other hand.
- **Remove short rests** (gaps shorter than a 16th note). Ticked at the start. Notes that carry a mark are left alone.

Press **Run**. When it is done, the program shows the same report as **Compare with Original** (below), with the buttons **Keep** and **Undo all of this**.

## Separate Hands (piano, organ, accordion…)

**Fix File ▸ Separate Hands…** sorts the notes into a **right-hand staff** and a **left-hand staff**, the way a printed piano score looks. It works for any two-handed keyboard-style instrument: one hand plays the higher notes, the other the lower. A file that is already on two tracks (right hand and left hand) is recognised without this step.

- **Which instrument.** It sorts keyboard instruments only: pianos, harpsichord, clavinet, celesta, organs and accordion. A file with none of these (a violin concerto, say) gets the message "This file has no keyboard instrument" and nothing is changed. If the file holds exactly one keyboard instrument, that one is sorted without a question. If it holds several, a list shows each one with its number of notes, its range and its track numbers. The likely keyboard is marked and preselected, and nothing is split until you press **Continue**. Check what the list says: a clavinet, for example, counts as a keyboard even in a funk file where it plays single notes.
- **Help.** Every Separate Hands and Fix Chords window has a **Help** button (or press **F1**) that opens this guide at the right section.
- It asks two questions about the player's hand:
    - **Widest stretch of one hand**, in semitones (a semitone is the distance between neighbouring piano keys; 12 is one octave). The standard value is **12**. It can be raised for large hands (up to 30) or lowered for small hands such as a child's (down to 6).
    - **Most notes one hand plays at once.** The standard value is **5**, one per finger. It cannot go above 5. Lower it if a hand is injured, for example to 4, or to 1 for one finger.
- It decides by pitch and by how far a hand can reach.
- **Chords of more than five notes, or too wide.** No hand has six fingers. When the split is finished, the program tells you how many measures hold chords one hand of that size cannot play, and **asks whether to open Fix Chords**.
- **It does not change how the music sounds.** Every note keeps its original start, length and loudness. Pedal markings are kept. Other instruments in the file, such as drums and bass, are left exactly as they were. Only the piano part is split.
- If the file is already on two staffs, the program asks before splitting it again.
- To go back, use **Edit ▸ Undo**.
- **Check the result.** The split is worked out from the notes alone and can put a note in the wrong hand, or give one hand a passage it cannot play. Check it by ear and eye with an expert such as a music teacher or performer.

## Fix Chords

After the hands are separated, some chords may still be wider than one hand can hold (for example 16 semitones) or have more than five notes. **Fix File ▸ Fix Chords…** asks the same two hand questions as Separate Hands and lists those chords, one line per chord, with the measure number. A perfectly prepared file may list only a few lines; a performance may list many.

For each line you choose what to do:

- **Move** a note to the other hand, when that note fits within the other hand's stretch and that hand is free. Nothing is lost. This is offered first.
- **Leave out** (delete) a note.
- **Keep** the chord as it is.
- **Roll signs.** Four or more notes struck one after another very quickly are a *rolled chord*. These are shown separately, and you can accept the roll sign instead of changing the notes.

How to use the window:

1. Click a line to see that measure in the score. **Change…** lets you choose per note, and the note lights up in the score.
2. **Hear original** and **Hear changed** play that measure both ways. **Stop** ends it.
3. Tick **Fix** to make the change in the score now. Untick it to take it back. Each tick is one **Edit ▸ Undo** step.
4. Tick **Final** when a line is finished. A Final line is **locked**: it cannot be unticked, and later changes in the window leave it alone. Ticking Final on a line you did not change means "leave this one exactly as recorded".
5. **Fix all roll signs**, **Fix all leave-out / move** and **Fix all remaining** do many lines at once. **Lock all changed** makes every changed line Final.
6. **Add selection**: in the Score, use the **Select** tab to select some notes, then press **Add selection** to make a line for them. Use it for notes you have moved by hand.
7. Changing one chord can make a neighbouring chord too big. The window says when new lines were found, and **Check again** looks again.

The title says how many lines are still open. Only the score changes; the sound is as recorded.

## Fix Measures

**Fix File ▸ Fix Measures…** lists each staff in each measure where the music runs past the barline. Pick a line to see that measure and the measures on either side of it, with how many beats each one holds. Tick **Also list measures that stop short of the barline** to see those too (a measure that simply ends in a rest is normal, so they are off to begin with). Then choose a fix:

- **Cut at the barline**: a note that runs past the barline stops at it.
- **Tie over the barline**: the program splits the note at the barline and ties the rest into the next measure.
- **Lengthen to the barline**: for a measure that stops short, the last chord is made to last until the barline.
- **Move this measure's notes (this staff) earlier or later** by a step you choose.

Each fix is one **Edit ▸ Undo** step. The window also has **Undo** and **Refresh list** buttons. Notes that are tied over a barline on purpose, such as a long held note, appear in the list too; leave those alone if they look right.

## Remove Short Rests

**Fix File ▸ Remove Short Rests…** closes the sliver gaps described above. It makes the note before each short gap last until the next note, so the rest disappears. No note is added, moved or removed.

1. **Remove rests shorter than:** choose **1/16**, **1/8** or **1/4**. Start with 1/8 and look at the score.
2. **Measures:** choose **All**, or **From … to …** to work on one passage.
3. A line shows how many gaps would be closed. Click **Remove**.

- **The sound stays exactly as recorded.** Only the score changes; playback and the saved MIDI file are unchanged.
- A gap that crosses a barline is closed with a **tied** pair of notes.
- Notes that are already in a tie are left alone.
- **Edit ▸ Undo** puts everything back exactly.

## Rationalize Score

**Fix File ▸ Rationalize Score… (Ctrl+R)** works out the hands, the measures and the time signature for a human-played file in one step.

At the bottom is a green tick box: **Keep the original sound (recommended)**. With it ticked, every note keeps its original start, length and loudness, the speed is never changed, and other instruments are untouched. With it **un-ticked**, notes are snapped and shortened to match the tidied score, so the sound changes. Choose that only if you want the cleaned version to be what you hear.

| Setting | What it means |
|---|---|
| **Auto-detect tempo** / tempo box | Estimates the real speed of the performance (only when "Keep the original sound" is off). |
| **Time-Sig-auto-detect** and the two number boxes | Guesses the time signature, or lets you type it. |
| **Preserve existing hand tracks** | If the file already has a right-hand and a left-hand track, keep them as they are. |
| **Hold notes while the sustain pedal is down** | Makes notes last as long as the pedal holds them (only when "Keep the original sound" is off). |
| **Quantize strength / grid** | How firmly notes snap to the beat grid (only when "Keep the original sound" is off). |
| **Remove rests shorter than** | Off, 32nd, 16th, 8th or quarter. For a file you have already rationalized, use **Remove Short Rests** instead. |
| **Max hand span** | How far one hand can reach. |
| **Arpeggio window** | How close together in time notes must be to count as one chord. It is measured in *ticks*, the tiny time steps inside a MIDI file. The standard value is **0, which means automatic**: the program uses about 20 thousandths of a second (1/50 of a second) at the speed of your piece. A larger number gathers more spread-out notes into one chord. A smaller number keeps them as separate notes. Leave it at 0 unless a fast run of notes is being merged into a chord, or a rolled chord is not being recognized. |
| **Whole piece** / measure range | Rationalize everything, or only some measures. |

The buttons are **Preview** (run it and play the result), **Accept** (keep it), **Discard** (throw it away and return to your original), **Save copy…** and **Close**. Hover the mouse over any setting for a short explanation.

## Compare with Original

**Fix File ▸ Compare with Original…** reports how the score now differs from the file as you opened it. It only looks; nothing changes. It says:

- **Sound (what you hear):** the same as the loaded file, or **different**, with how many notes are missing, new, or changed in length or loudness. Repairs that change only the written score keep this "the same".
- **Strikes per bar:** the same in every bar, or the bars that differ. This is how you check that a repair did not add or remove a note.
- **Notes:** how many when loaded and now (a tied note counts once).
- **Hands:** how many notes the right hand and the left hand have, or that the score is not split.
- **Score only:** how many notes are drawn longer than they sound (from **Remove Short Rests**). The sound is kept.
- **Marks:** how many notes carry a mark.
- **Key, time signature, tempo:** unchanged, or what changed.

It works on a score opened from a MIDI file. A new, empty score has nothing to compare with.

# 8. Playing: hands, fingers and marks

The **Playing** menu holds tools that help a person play or read the music. Like the **Fix File** tools, they change the written score only: the sound stays as recorded and **Edit ▸ Undo** takes each one back (except where noted).

**Please read: these are suggestions, and they can be wrong.** Hands, fingers and marks are worked out from the notes alone. They can produce impossible results: hands or fingers that cannot be played. Check them by ear and eye with an expert such as a music teacher or performer. In the program's own tests the weakest places were left-hand scales over two octaves, and music where the hands cross or a melody lies low on the keyboard. The tools are being improved.

## Easy to Play (hand over hand)

**Playing ▸ Easy to Play (hand over hand)…** finds places where one hand keeps a trill or a repeated group of notes while the melody weaves above and below it. A split by pitch gives that melody to the wrong hand. Each line in the window says which hand should hold the figure and which the melody, chosen by where each hand has to be before and after.

- Only the staff changes; the sound is exactly as recorded.
- Nothing changes until you press **Apply selected** or **Apply all**.
- **Edit ▸ Undo** takes it back.
- It needs the music in two hand parts. If the file is not split, the program tells you to run **Separate Hands** first. It then asks the same two hand questions as Separate Hands (widest stretch, most notes at once).

## Fingering Numbers

**Playing ▸ Fingering Numbers…** shows suggested fingers on the Score, in blue: **1 is the thumb and 5 the little finger**, for each hand. Choose one of three settings:

- **Off**
- **Only where they matter** (the start of a run, thumb crossings, leaps, wide chords)
- **Every note**

Things to know:

- **It starts Off for every file you open.** The setting is not saved in the file.
- **It cannot be edited note by note.** It is on or off, nothing else.
- **It is a suggestion from the notes alone,** not a teacher's fingering. It follows common rules: the thumb passes under the fingers going away from it, and the fingers cross over the thumb coming back, mirrored for the left hand. The thumb passes under finger 3 in preference to finger 4, and two different keys played close together are not given the same finger.
- **How it is worked out.** The program looks for the easiest fingering of the whole passage, not note by note, using the published cost rules of Parncutt, Sloboda, Clarke, Raekallio and Desain ("An ergonomic model of keyboard fingering for melodic fragments", Music Perception 14, 1997), plus the usual textbook fingerings for scales and chords. It was checked against the 24 major and minor scales, and compared with pianists' fingerings in the PIG data set (Nakamura, Saito and Yoshii, "Statistical Learning and Estimation of Piano Fingering", Information Sciences 517, 2020), used with the authors' permission for evaluation only. That data is not part of this program.
- **The numbers also appear in the printed score and in the MusicXML export** (section 9), following your setting. Nothing changes in the music, and nothing is saved in the MIDI file.
- **It needs two hands.** If the file is one track with both hands, the program offers to run **Separate Hands** first. If there are several tracks, it asks you to use **Tracks ▸ Combine Tracks**, then **Separate Hands**.
- **Check it** by ear and eye with an expert such as a music teacher or performer, as described at the top of this section.

## Suggest Marks

**Playing ▸ Suggest Marks…** looks for two things in how the music was played: runs of short, separated notes (it suggests **staccato**) and notes much louder than their neighbours (it suggests **accent**). Other marks (tenuto, portato, fermata, tremolo, marcato, pizzicato) cannot be told from a recording; set those yourself on the **Articulation** tab.

- Nothing changes unless you tick a kind and press **Add Marks**.
- Marks change the written score only. A marked note keeps its gap, **Remove Short Rests** leaves it alone, and it prints with its sign. The sound stays as recorded.
- When the program thinks there are marks to suggest, the status bar says **Marks suggested: Playing > Suggest Marks**.
- **Edit ▸ Undo** takes the marks back.

## Marks on notes

A mark belongs to a note: it says how the composer wants it played. Select notes in the Score, open the **Articulation** tab, pick a mark and press **Apply to Selection**. Pressing it again with the same mark takes the mark off. The marks are:

| Mark | Meaning |
|---|---|
| **Staccato** | Short and detached. |
| **Staccatissimo** | Very short and detached. |
| **Accent** | Played with more force. |
| **Tenuto** | Held for its full length. |
| **Portato** | Slightly detached, between smooth and staccato (a dot with a dash). |
| **Marcato** | Strongly accented. |
| **Pizz.** | Plucked (shown as "pizz."). |
| **Fermata** | Hold the note longer (a pause). |
| **Tremolo** | The note is repeated very rapidly. |

Marks appear on the Score, in the printed score and in the **MusicXML** export. They do not change the sound. (The Articulation tab also offers **Legato** and **Arco**; they are not covered here.)

## Soft Notes

**Playing ▸ Soft Notes…** finds single notes (not part of a chord) played so softly they are hardly heard, while the notes around them are several times louder: usually a key touched by accident.

- **Velocity at or below** (loudness on MIDI's 1–127 scale; starts at 20) and **Neighbours louder by at least** (starts at 3 times) set what counts as soft.
- **Show in red** marks them on the Score. **Nothing changes** until you press a button.
- **Delete them** removes the notes from the sound **and** the score. **Raise them** makes them louder, which changes the sound. **Edit ▸ Undo** restores them.

# 9. Printing a score

**File ▸ Print Score (via LilyPond)…** makes a printable Portable Document Format (PDF) file with LilyPond, a free music-engraving program. **File ▸ Export ▸ LilyPond (.ly)…** saves the LilyPond file if you want to use it elsewhere.

**Getting LilyPond.** LilyPond for Windows is not an installer, just a folder. The first time you print, if the program cannot find it, a window offers three choices:

- **Download and set it up for me** (Windows). The program downloads LilyPond (about 45 megabytes) into your own user folder and starts using it. You do not need to do anything else.
- **I already have it – find lilypond…** Pick `lilypond.exe` from the `bin` folder of a LilyPond you already have. The program remembers it.
- **Not now.**

On Linux, install LilyPond with your package manager (`sudo apt install lilypond`, or `sudo pacman -S lilypond`). On a Mac, use `brew install lilypond`.

The program also looks in your home folder, Downloads, and Program Files, so a LilyPond you unpacked yourself is usually found automatically.

**What the printed score shows**

- The **title** and **composer** you typed in **Score Settings** (section 6) are printed at the top. If you left the title alone, the file's name is used.
- The name of each instrument appears in small print **above its staff, at the left margin**, on every line of music. The first line has the full name; later lines have a short one (for example "Violin" then "Vln."). Staffs that would share a name are numbered ("Violin 1", "Violin 2").
- A name you typed (in the track list or the Mixer) is printed as you typed it. A default label such as "Track 3" is replaced by the instrument sound chosen for that track, and the drum track prints as "Drums".
- Measure numbers are printed above the top staff and apply to every staff beneath them. The vertical barlines run through all the staffs, so you can follow one measure straight down the page. Tick or untick **Show measure numbers** in the print options.

# 10. Something not working?

**I hear no sound.** Open **Setup ▸ MIDI Output Device…** (MIDI is Musical Instrument Digital Interface) and pick another choice. **FluidSynth (built in)** is usually best on Windows, Linux and Mac. **Setup ▸ MIDI I/O Info** shows what the program found.

**The drums sound wrong.** Open the **Mixer** and turn the drum track's volume down, or check that the drums are on **channel 10**, which is the drum channel.

**The program takes a long time to start.** It loads all the instrument sounds first. An older computer can take about 12 seconds. This is normal.

**The sound or the red line stutters.** Use **Follow: Page** (it is the default). If you chose Smooth and your computer is slow, the program switches to Page by itself.

**Printing says LilyPond was not found.** Use the window that appears (section 9).

**The program will not start on Windows.** Make sure you extracted the whole zip (**Extract All**), or use the installer instead.

**The red line ran off the screen.** Press **⏹ Stop**, then **⏮**, then Play again. If it keeps happening, please tell me exactly what you did just before.

**I want to keep the original.** Always use **File ▸ Save As…** and give a new name.

**There are lots of tiny rests in the score.** That is normal for a recorded performance (section 7). Leave **Short rests** unticked to hide them, or use **Fix File ▸ Remove Short Rests…**.

**A correction window disappeared.** Newer windows open on top of older ones, but you can still drag an older window over a newer one. Look for the window you want and click it.

**Anything else.** Use **Help ▸ Send a Problem Report…** (section 11), or email me at **winthrom@hotmail.com**. Please say which computer you use (Windows 10, Windows 11, a Mac, or the name of your Linux), what you clicked, and what you saw. A photo of the screen helps.

# 11. Telling me about a problem

**The Tester Log.** While you use the program it keeps a short diary of what it did: which menu items you used, how many notes and measures the piece had before and after each correction tool, and any error message. It is stored **only on your computer**, in a folder called `.midistudio_logs` in your home folder, one file for each time you used the program; the last 20 are kept. It does not record the music itself, and file names are kept without their folders. **The program never sends it anywhere.**

It is on by default. To turn it off or look at it, use **Help ▸ Tester Log ▸ On / Off / Show the log folder**.

**Help ▸ Send a Problem Report…** makes one **zip file** you can email:

1. Type what went wrong and what you expected.
2. Tick **Also include the piece that is open** only if you are happy to share the music. Otherwise leave it unticked.
3. Click **Create the report**. The zip appears on your Desktop (or in your home folder). The window shows where.
4. Email that zip to the person who gave you MIDI Studio, or to **winthrom@hotmail.com**.

The zip holds your note, the recent logs, and basic details of your computer (the program version, the system, the screen size). A report like this is the most useful thing you can send: it shows exactly what happened, in order.

# 12. Names, trademarks and what has been tested

MIDI Studio's code and this guide are free software under the GNU General Public License, version 3 or later. That licence does **not** cover names, logos or emblems that belong to other organisations. The Lions name and emblem are trademarks of Lions Clubs International; MIDI Studio is made by a member of the Sterling Lions Club and links to the club's website, which is not an endorsement by Lions Clubs International. The exact terms are in the file **TRADEMARKS.md** on the project page.

Other product and company names mentioned in this project (MuseScore, MidiSoft Studio, Microsoft, Windows, Apple, macOS, Linux, LilyPond, FluidSynth and so on) belong to their owners. They are used only to say what the program may work with, and no endorsement or connection is implied.

MIDI Studio is an independent work-alike. It contains no code from MidiSoft Studio.

**Music, recordings and copyright.** MIDI Studio makes no claim over anything you record or create with it. The program is only a tool: its licence covers the program, not your files. The rights in a piece of music stay with whoever owns them, which may be the composer, or no one if the music is in the public domain. A performance you play and record is normally yours; if more than one person is involved, agree in writing who owns it. Playing a protected piece for yourself is private, but sharing a recording or a score of it needs the owner's permission. Modern editions and arrangements of old music can be protected even when the music itself is not. This note is general information, not legal advice.

**Compatibility notes:** MIDI Studio's MusicXML export has been tested by opening the files in MuseScore. It has not yet been tested whether a MIDI file saved by MIDI Studio opens in MidiSoft Studio, and the program has not yet been tested on macOS.

# Words used in this guide

- **Measure** (also called a **bar**): one short section of music between two vertical lines on the staff.
- **Barline**: the vertical line between measures.
- **BPM**: Beats Per Minute, the speed.
- **Staff** (plural **staffs**): the five lines that the notes sit on. One per instrument, or two for a keyboard instrument such as a piano.
- **Treble and bass clef**: the symbols at the start of a staff. Treble is for higher notes, usually the right hand; bass is for lower notes, usually the left.
- **Time signature**: two numbers such as 4/4 that say how many beats are in each measure.
- **Key signature**: the sharps or flats at the start of the staff that say which notes are raised or lowered throughout.
- **Tempo**: the speed of the music.
- **Track**: one instrument's line of music in the file.
- **Quantize**: nudge notes onto an even beat grid.
- **Short rest** (or **sliver**): a very small gap between two notes, usually because a player lifted a finger a moment early. Common in recorded performances; absent in hand-made files.
- **Hand-made MIDI file**: a file typed in or drawn note by note, so every note starts exactly where the last ended. The opposite of a recorded performance.
- **Staccato**: a short, detached note.
- **Accent**: a note played with more force.
- **Tenuto**: a note held for its full length.
- **Portato**: a note slightly detached, between smooth and staccato.
- **Fingering**: which finger plays which note. 1 is the thumb, 5 the little finger.
- **Listening speed**: playing the music slower or faster for your ears only, without changing the music or the file.
- **Sustain pedal**: the piano pedal that lets notes keep ringing after the key is released.
- **Chord**: several notes played together.
- **Rolled chord**: a chord whose notes are struck one after another very quickly, like a harp.
- **Arpeggio**: the notes of a chord played one after another.
- **Tie**: a curved line joining two notes of the same pitch into one longer note.
- **Dynamics**: how loud or soft: p (soft), mf (medium loud), f (loud).
- **MIDI**: Musical Instrument Digital Interface, the standard way instruments and computers exchange music.
- **PDF**: Portable Document Format, a file that looks the same on every computer.
- **Synthesizer**: the thing that turns the MIDI instructions into sound.
- **LilyPond**: the free program that draws the printed score.

---

# Index

Topics in alphabetical order. The same list is searched by **Help ▸ Where do I find…?** in the program.


**A**

- Accent: [Marks on notes](#marks-on-notes)
- Add Track / Delete Track: [The menus](#the-menus)
- Arco: [Marks on notes](#marks-on-notes)
- Auto-Correct Score: [Auto-Correct Score](#auto-correct-score)

**B**

- Barlines in the wrong place: [When the measures are the wrong length](#when-the-measures-are-the-wrong-length)
- BPM (beats per minute): [BPM, tempo change and listening speed](#bpm-tempo-change-and-listening-speed)
- Braille music: [The menus](#the-menus)

**C**

- Chords too wide for one hand: [Fix Chords](#fix-chords)
- Combine Tracks: [The menus](#the-menus)
- Compare with Original: [Compare with Original](#compare-with-original)
- Composer: [Setting the speed, time, key and title](#setting-the-speed-time-key-and-title)

**D**

- Drums: [Something not working?](#something-not-working)

**E**

- Easy to Play (hand over hand): [Easy to Play (hand over hand)](#easy-to-play-hand-over-hand)
- Editing tabs: [The editing tabs](#the-editing-tabs)

**F**

- Fermata: [Marks on notes](#marks-on-notes)
- Fingering numbers: [Fingering Numbers](#fingering-numbers)
- Fix Chords: [Fix Chords](#fix-chords)
- Fix Measures: [Fix Measures](#fix-measures)
- Follow: Page / Smooth: [Buttons at the top of the Score](#buttons-at-the-top-of-the-score)

**G**

- Grace Cleanup: [The menus](#the-menus)

**H**

- Hands, separating: [Separate Hands (piano, organ, accordion…)](#separate-hands-piano-organ-accordion)
- Hear selected notes: [The menus](#the-menus)

**K**

- Key signature: [Setting the speed, time, key and title](#setting-the-speed-time-key-and-title)

**L**

- LilyPond: [Printing a score](#printing-a-score)
- Lions Club and trademarks: [Names, trademarks and what has been tested](#names-trademarks-and-what-has-been-tested)
- Listening speed: [BPM, tempo change and listening speed](#bpm-tempo-change-and-listening-speed)

**M**

- Marks on notes: [Marks on notes](#marks-on-notes)
- Measures wanted: [When the measures are the wrong length](#when-the-measures-are-the-wrong-length)
- Metronome click: [The row of buttons across the top](#the-row-of-buttons-across-the-top)
- MIDI output device (no sound): [Something not working?](#something-not-working)
- Mixer: [Four ways of looking at the music](#four-ways-of-looking-at-the-music)
- MusicXML: [The menus](#the-menus)
- Mute and Solo: [The track list](#the-track-list)

**N**

- Names of other products: [Names, trademarks and what has been tested](#names-trademarks-and-what-has-been-tested)

**P**

- Pedal marks: [Buttons at the top of the Score](#buttons-at-the-top-of-the-score)
- Piano Roll: [Four ways of looking at the music](#four-ways-of-looking-at-the-music)
- Portato: [Marks on notes](#marks-on-notes)
- Print a score: [Printing a score](#printing-a-score)
- Problem report: [Telling me about a problem](#telling-me-about-a-problem)

**Q**

- Quantize: [Quantize](#quantize)

**R**

- Rationalize Score: [Rationalize Score](#rationalize-score)
- Recording from a keyboard (Rec): [The row of buttons across the top](#the-row-of-buttons-across-the-top)
- Remove Short Rests: [Remove Short Rests](#remove-short-rests)

**S**

- Save As: [The menus](#the-menus)
- Score Settings: [Setting the speed, time, key and title](#setting-the-speed-time-key-and-title)
- Short rests (show or hide): [Buttons at the top of the Score](#buttons-at-the-top-of-the-score)
- Soft Notes: [Soft Notes](#soft-notes)
- Staccato: [Marks on notes](#marks-on-notes)
- Suggest Marks: [Suggest Marks](#suggest-marks)

**T**

- Tempo change (%): [BPM, tempo change and listening speed](#bpm-tempo-change-and-listening-speed)
- Tenuto: [Marks on notes](#marks-on-notes)
- Tester Log: [Telling me about a problem](#telling-me-about-a-problem)
- Time signature: [Setting the speed, time, key and title](#setting-the-speed-time-key-and-title)
- Tremolo: [Marks on notes](#marks-on-notes)

**U**

- Undo and Redo: [The menus](#the-menus)
- Uninstall: [Removing the program](#removing-the-program)
- Updates (Check for Updates): [The menus](#the-menus)

**W**

- Windows warning (protected your PC): [Windows 10 or 11 (64-bit)](#windows-10-or-11-64-bit)

**Z**

- Zoom and Fit Width: [Buttons at the top of the Score](#buttons-at-the-top-of-the-score)

# Afterword: About MIDI files

## What is MIDI?

A Musical Instrument Digital Interface (MIDI) file, ending in `.mid`, is not a recording. It is a list of instructions: "play this note, this loud, starting now, for this long." Most music players can play one. MIDI Studio reads that list and draws it as sheet music. You can then:

1. Hear the music play.
2. See the music notation (the score), with a red line moving across it to show the notes being played.
3. Zoom the score in and out.
4. Change the tempo.
5. Mute instruments. This is useful for practice if you play an instrument in a group such as a band.
6. Make your own score by playing a MIDI instrument, with MIDI Studio as the recorder.
7. Tidy the score.
8. Print it.

## Why MIDI?

1. MIDI files are very small compared with audio files, which is good for email.
2. An audio file is a "final" product that is very hard to change.
3. MIDI makes creativity much easier.

## Where do I get MIDI files?

1. Make them with a MIDI instrument, such as an electronic keyboard.
2. Record an audio file and have an online program convert it to a `.mid` file.
3. Look for free MIDI files online. Tens of thousands are available, of all kinds of music.

## Limits of MIDI

1. A MIDI file holds no sounds of its own. The program that plays it uses pre-recorded instrument sounds.
2. Those pre-recorded sounds may not sound as good as your own instrument.
3. Almost anything that can make a sound is used in music (washboards, spoons and so on), but the list of available pre-recorded sounds may not include an odd instrument from your audio recording (to convert to `.mid`) or from a MIDI file you found online.
4. Some instruments, keyboards for example, record only one track, even though a musician needs a track for each hand to make a score another musician can play from. MIDI Studio has tools to fix that: see [Separate Hands](#separate-hands-piano-organ-accordion).

---

*MIDI Studio is free software (GNU General Public License, version 3 or later), made to support the Sterling Lions Club of Virginia. Comments and corrections are welcome.*
