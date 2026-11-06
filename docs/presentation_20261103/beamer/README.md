# Build the English Beamer report

The [17-slide PDF](../Adversarial_Fact_Verification_Revised.pdf) uses the three vector figures in `assets/`. The [source](adversarial_fact_verification_revised.tex) includes English speaker notes and the timing for each slide.

Run these commands from this directory with TeX Live, including Beamer, TikZ and textpos. The checked-in figures are sufficient for a clean build.

```powershell
New-Item -ItemType Directory -Force -Path build | Out-Null
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build adversarial_fact_verification_revised.tex
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build adversarial_fact_verification_revised.tex
Copy-Item -LiteralPath 'build/adversarial_fact_verification_revised.pdf' -Destination '../Adversarial_Fact_Verification_Revised.pdf'
```

To regenerate the figures and their source manifest, use Python, Matplotlib and NumPy. The generator reads the frozen results in `worktrees/A_B_fusion_v18`. Set up that [worktree](../../worktree_locations.md) if needed, then run `python generate_assets.py` from this directory. The generator checks the result hashes and correct counts against the stored predictions. Intermediate files go in the ignored `build/` directory.
