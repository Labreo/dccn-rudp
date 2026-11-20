# Mini project report

| File | What it is |
|---|---|
| [RUDP_Mini_Project_Report.pdf](RUDP_Mini_Project_Report.pdf) | The report, ready to read or print (46 pages) |
| [RUDP_Mini_Project_Report.docx](RUDP_Mini_Project_Report.docx) | Same report in Word format, to fill in college name, roll numbers and guide |
| [figures/](figures/) | Design diagrams: architecture, use case, class, sequence, state, flowcharts, DFDs |
| [diagrams/](diagrams/) | Mermaid source of those diagrams |
| [screenshots/](screenshots/) | Screenshots of real runs (terminal and live visualizer), with the terminal text in `.txt` |

The report follows the required structure: Abstract, Introduction, Motivation,
Analysis and Design, Implementation Details, Testing, Running Code and
Execution, Results and Screenshots, Conclusion and Future Scope, References.

To regenerate the figures and screenshots (needs `pip install playwright` and
`playwright install chromium`; diagrams need internet for Mermaid):

```bash
python report/make_figures.py
python report/make_screenshots.py
```
