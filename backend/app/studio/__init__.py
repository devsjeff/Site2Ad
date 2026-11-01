"""Studio: a staged pipeline that makes a typed video (promo, hook ad, pitch, showcase, explainer, testimonial, launch).

capture -> product notes -> brand notes -> assumptions -> storyboard -> build -> check

Every stage reads the files the stage before it saved in the run folder and saves its own, so any stage can be re-run
or hand-edited. See README.md in this folder.
"""
