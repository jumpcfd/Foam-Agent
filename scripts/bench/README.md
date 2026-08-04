# Running FoamBench with this fork

[FoamBench](https://github.com/NLR-Theseus/cfdllmbench) scores an OpenFOAM workflow from
natural language: 110 basic and 16 advanced cases, each a request and a reference case.
These scripts produce submissions with this fork and hand them to the benchmark's own
evaluator unchanged, except for one patch recorded here.

Nothing under `~/foambench` is part of this repository: the dataset is someone else's data
and the results are machine state. Only the scripts live here.

## What you need

- OpenFOAM 10, which is what the reference cases were written for. The `docker` runtime is
  the least trouble: `foamagent config set openfoam.runtime docker`
- The catalogue built for it: `foamagent index build`
- The harness CLI on PATH
- pandas, pyvista and rouge-score **for the evaluator only**. They are not dependencies of
  Foam-Agent; `uv run --with` fetches them for the one command that needs them

## 1. Get the dataset and unpack it

```bash
mkdir -p ~/foambench/Dataset && cd ~/foambench
curl -L -o foambench.zip \
  "https://www.kaggle.com/api/v1/datasets/download/nithinsekhar/foambench"
unzip -q foambench.zip -d Dataset/

python <repo>/scripts/bench/foambench_unpack.py Dataset/FoamBench_advanced.json
```

That writes, per case, `usr_requirement.txt` and `GT_Files/`. The official
`read_json_advanced.py` also writes a YAML holding a MetaGPT path, an OpenAI key and a
model name; none of it applies here, so this does not.

## 2. Run the reference cases

```bash
python <repo>/scripts/bench/foambench_reference.py Dataset/Advanced
```

**This step is not in the benchmark's instructions and cannot be skipped.** The references
ship as input files only. The evaluator's NMSE reads the reference with PyVista and takes
its *last* time; on an unrun reference that last time is 0, and every submission is scored
against the initial condition rather than against a solution.

## 3. Produce the submissions

```bash
python <repo>/scripts/bench/foambench_run.py Dataset/Advanced --case Cavity_SA
```

One non-interactive harness session per case, started in a directory this writes
(`~/foambench/harness`) with `.mcp.json`, the skill, and a `foamagent.yaml` that sets
`review.mode: 'off'`. The request is passed word for word; the only text added to it says
where to put the case and that nobody is available to answer questions. Both the prompt and
the verbatim request are recorded in `<case>/foamagent-run.json`.

Reviews are off because sixteen cases at two reviews and a report each is upwards of ten
hours of model time, and no metric reads any of it. A case run this way has had no
independent check: that is a property of the benchmark run, not of the tool.

## 4. Score

```bash
cd ~/foambench
cp <repo>/scripts/bench/../../scripts/bench/score_calculation.patch .   # or fetch the four scripts
uv run --with pandas python execution_report.py
uv run --with rouge-score python similarity_report.py
uv run --with pandas --with pyvista python nmse_report.py
uv run --with pandas python score_calculation.py       # after applying the patch below
```

The four scripts come from the benchmark repository and are used as they are, with one
exception: `execution_report.py` writes its column as `Success` and `score_calculation.py`
reads it as `Execution`, so the final step raises `KeyError` before writing anything.
`score_calculation.patch` in this directory fixes that and nothing else.

`Dataset/Basic` must exist even when only the advanced split is being run: every script
walks both.

## What the evaluator requires of a submission

Worth knowing, because two of its requirements pull in opposite directions.

| Script | What it looks at |
|---|---|
| `execution_report.py` | `log.*Foam` in a **subdirectory** of the submission, whose second-to-last line is `End`. A log at the submission's root is never seen |
| `similarity_report.py` | `0/`, `constant/`, `system/` at the submission's **root**, compared file by file against the reference (ROUGE-L, and the fraction of reference files present at the same path) |
| `nmse_report.py` | The submission's root read as an OpenFOAM case, `U`/`p`/`rho`/`T` at the reference's last time |
| `score_calculation.py` | Success Ratio counts a case only if it both ran and scored NMSE < 0.1 |

An ordinary OpenFOAM case satisfies the last three and fails the first, because OpenFOAM
writes `log.pisoFoam` next to `system/`. `foambench_run.py` copies each log into
`<submission>/logs/` as well, which the other three ignore. This was measured, not
inferred: a submission that was a byte-for-byte copy of a run reference case scored
`Execution=0` until the copy existed, and 1.0 across all four metrics afterwards.

The submission directory is found as "the first directory that is not `GT_Files`", so there
must be exactly one. Keep working copies elsewhere.

## Comparing against the published numbers

Do not, without saying what differs. The published FoamBench results are MetaOpenFOAM
driving `gpt-4o` at temperature 0. A run here is a different framework on a different model,
scored after a patch to the scoring script and with a log-placement fix that the reference
implementation may or may not need. Report the model, the framework, the evaluator commit
and every deviation alongside any number produced here.
