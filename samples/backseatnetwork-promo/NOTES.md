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
* Later upgrade: the capture (`01_capture`) was run again with the current capture stage (it hides floating chat widgets, drops empty
  screenshots and saves the site's logo as `01_capture/assets/logo.png`), and the video was rebuilt with the current design: 1920x1080 at
  30 fps, the brand colour filling every other frame, a large browser window cropped to the real content, the logo on the end card and a
  close crop of a real screenshot beside the price and the call to action. The notes and storyboard are unchanged and the check still passes.

To see the automatic version, run the same command again after the AI limit resets:
`python -m app.studio run --url https://backseatnetwork.com --type promo --length 20 --platform 16:9`

The rendered frames (60 MB) were deleted to keep this folder small; `python -m app.studio build --run <this folder>` makes them again.
