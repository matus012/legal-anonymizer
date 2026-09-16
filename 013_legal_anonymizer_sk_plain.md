# The Anonymizer, plain and simple

## The problem it solves

When your office sends a contract, a lawsuit, or a land-registry extract to a court, a
counterparty, or a publisher, the document is full of things that identify real people:
names, birth numbers, addresses, bank accounts, phone numbers. Before that document can go
out, all of that needs to be blacked out — and doing it by hand, on every page, for every
document, is slow and easy to get wrong. Miss one mention of a name on page 4 and the whole
effort was for nothing.

This tool reads a Word document or a PDF, finds the things that identify people, and produces
a new copy with all of that removed — replaced with a label like `[MENO_1]` so you can still
tell "this is the same person mentioned three times" without knowing who they are. It runs
entirely on your own computer. Nothing about the document ever leaves your machine, unlike
uploading it to a website that offers to "anonymize" it for you.

## How it is used, day to day

1. Open the program. Drag in one or more files — Word documents or PDFs.
2. Optional but strongly recommended: type in the names and address of the client and the
   other party before scanning. You already know who they are; telling the tool costs you one
   text box and makes it dramatically more reliable at catching every mention of them,
   including the ones written a little differently ("Ján Novák" on one page, "p. Novák" on
   another).
3. Click scan. The tool splits what it found into two lists: things it is confident about
   (already ticked, ready to remove) and things it is not sure about (unticked — it wants you
   to decide). Both lists are grouped by person or item, not by every single occurrence, so
   you are not stuck reviewing the same name forty-seven times.
4. Look through the "not sure" list. Tick anything that should also be removed. There is also
   a free-text box for typing in anything the tool missed entirely.
5. Export. You get a new file — the original is never touched — plus a written report
   listing everything that was removed and where. Keep that report; it is your record of what
   was done to that document.
6. Read the report against the document before you send it anywhere. This step is not
   optional, and it is not there to cover for the tool being unreliable — it is there because
   no automated tool, including this one, can promise perfection, and a human check is the
   only thing standing between an automated mistake and a document leaving the office.

## What it cannot do — and you must still check

- **It cannot read a scanned document or a photograph of a page.** If a PDF is just a picture
  of text (nothing can be selected or searched in it), the tool will refuse to process it
  rather than pretend to. You would need to convert it to real text first, or handle it by
  hand.
- **It cannot remove a signature or a stamp.** Those are pictures, not text, and the tool
  genuinely cannot see what a picture contains. If a document has a handwritten signature or
  a round office stamp that should not be sent out, you have to deal with that yourself —
  black it out in an image editor, print and re-scan, whatever your usual process is.
- **It does not decide what counts as a "trade secret" or "classified information."** The law
  requires those to be removed too, but deciding whether a particular sentence reveals a trade
  secret takes understanding what the sentence means — something no automatic pattern-matching
  tool can do reliably. That judgment call stays with the lawyer reviewing the document, every
  time.
- **The output PDF will not look as polished as the original.** Removed text becomes a black
  box with a label in it, at exactly the size and place the original text was — the rest of
  the page does not reflow around it. This looks a little clunky, but it is the only way to be
  sure the original words are truly gone from the file rather than just hidden under a drawn
  box (which would let anyone select the text underneath and read it anyway). Word documents
  reflow normally; PDFs do not.
- **It would rather remove too much than too little.** If it is unsure, it either removes
  something or flags it for you to look at — it never quietly leaves something in the text
  just because it was not fully sure. That means it will occasionally black out something that
  did not need to be blacked out. That is deliberate: a document with one extra black box is
  a minor inconvenience; a document that leaks a client's ID number is a real problem.
- **The file name itself can leak information.** A file called `Novak_kupna_zmluva.docx`
  reveals the client's surname the moment it lands in someone's inbox, no matter how carefully
  the contents were cleaned. The tool will warn you if this is the case — rename the file
  before sending it.
- **It never produces a "this document is 100% clean" guarantee.** What it produces is a
  detailed report of exactly what it changed and what it was unsure about. Reading and
  confirming that report before the document leaves the office is the actual safety check —
  the tool's job is to make that check fast and thorough, not to replace it.

If you are ever unsure about a specific document, ask the person responsible for the tool
before sending anything out.
