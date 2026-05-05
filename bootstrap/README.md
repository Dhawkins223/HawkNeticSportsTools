# HawkNetic project import

This folder contains a reconstruction script that writes the current HawkNetic BALLDONTLIE-canonical project into a local working directory.

## Why this exists
The GitHub connector available in this environment can write UTF-8 text files directly, but it is not a general binary ZIP uploader.  
So this script is the cleanest way to put the project **inside the repository** right now.

## What it does
Running `reconstruct_hawknetic_project.py` creates:

`hawknetic_balldontlie_canonical_project/`

with:
- FastAPI app
- website templates
- BALLDONTLIE provider layer
- raw-to-canonical mapping structure
- tests
- docs
- env template
- run entrypoint

It does **not** embed live secrets.

## How to use
From the repository root:

```bash
python bootstrap/reconstruct_hawknetic_project.py
cd hawknetic_balldontlie_canonical_project
pip install -r requirements.txt
python run_local.py
```

## Important
Put your real provider keys only in local environment files, not in committed source.
