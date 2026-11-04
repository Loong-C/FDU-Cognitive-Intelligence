# Beamer report

The English report has 15 main slides and 5 appendix slides. Its white background, blue tables, typography and page numbering follow the supplied Team A reference deck. The main slides include 602 words of English speaker notes in the LaTeX source; notes are hidden in the presentation PDF.

The source is `adversarial_fact_verification.tex`. The final PDF is saved one directory above as `Adversarial_Fact_Verification_Beamer.pdf`.

Rebuild from this directory with Python, Matplotlib, NumPy and TeX Live:

```powershell
python generate_assets.py
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build adversarial_fact_verification.tex
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build adversarial_fact_verification.tex
Copy-Item -LiteralPath 'build/adversarial_fact_verification.pdf' -Destination '../Adversarial_Fact_Verification_Beamer.pdf'
```

The chart generator reads frozen V17/V18 results and verifies their hashes and per-item counts. It makes no model calls and does not open the original test set. Chart PDFs under `assets/` are vector graphics. Evidence excerpts and labels come from `../slide_examples.json`.

Intermediate compilation files, render previews and provenance records are under `build/`. The main confusion matrix uses row-normalized percentages, including invalid outputs; the appendix shows counts for NLI and each LoRA seed, with the same 0–100% color scale.
