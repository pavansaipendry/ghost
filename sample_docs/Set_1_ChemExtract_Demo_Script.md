So — what is it? Chemists keep handwritten lab notebooks: messy
handwriting, drawings of molecules, calculations in the margins —
stuff no computer can read. We take a photo of the page and turn it
into clean, structured, trustworthy data you can search and
question.

How does it work? It's a vision-AI pipeline, built on Claude Opus
4.8, run in stages.

First it reads the page — several times, cross-checking the runs,
so anything that doesn't agree gets flagged instead of guessed.

Then a deterministic layer — pure code, no AI — fixes the units and
scientific notation that normally get mangled.

Then it identifies the hand-drawn molecules, using classic
recognition software only as a cross-check.

Then the key step: it reconstructs the experiment from the image
and re-does the math on the page to verify it actually holds. It
also pulls tables into rows and columns, and lays the page back out
in 2-D.

On top, a RAG layer lets you ask questions and get cited answers —
and refuses anything it can't source.

How well does it work? It catches errors people skim past, every
answer is traceable, and it runs at about sixteen cents a page.

&nbsp;

&nbsp;

&nbsp;

&nbsp;

&nbsp;

&nbsp;
