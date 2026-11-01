# Sample run: backseatnetwork.com, `promo`, 20 s, 16:9

Open `final.mp4`. The folder holds the files of every stage, in order (`01_capture` … `07_check`).

How this sample was made, honestly:

* Stages 1 to 5 were run with the real AI writer (OpenRouter). The page capture, the 19 sourced claims, the brand notes (primary `#ff6600`,
  Outfit and Inter, pill buttons, 24 px cards), the assumptions and the first storyboard are the AI's own output.
* The stage-7 checks then failed that storyboard, correctly: shot 3 compared the product with "Standard OOH: unverified" (no claim says that),
  and the voice lines of shots 1, 2, 4 and 5 were too long for their shots.
* The AI writer's free daily limit was used up by testing, so the checks could not rewrite those shots themselves. **I rewrote shots 1 to 5
  by hand in `05_storyboard.json`**, using only wording from the claims they cite (the intended workflow: any stage's file can be edited), then
  ran `build` and `check`. The check report is `07_check/report.md`: PASSED, 0 problems.
* Known flaw: the hero screenshot (`01_capture/screenshots/01_hero.png`) still shows the site's own "Planning a cab campaign?" chat widget.
  This capture was made before the capture stage learned to hide floating widgets; a new capture would not have it (but would renumber the
  citations, so the notes would have to be run again too).

To see the automatic version, run the same command again after the AI limit resets:
`python -m app.studio run --url https://backseatnetwork.com --type promo --length 20 --platform 16:9`

The rendered frames (60 MB) were deleted to keep this folder small; `python -m app.studio build --run <this folder>` makes them again.
