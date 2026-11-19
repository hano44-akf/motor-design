from pathlib import Path
p=Path(__file__).with_name('index.html')
s=p.read_text(encoding='utf-8-sig')
s=s.replace("['35PN','50PN'].includes(x)","['35PN','50PN',...steelCatalog.map(s=>s.grade)].includes(x)")
s=s.replace('</script></body></html>','</script><script src="steel-catalog.js"></script><script src="studio-v2.js"></script></body></html>')
p.write_text(s,encoding='utf-8')
