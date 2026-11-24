python pr2sound.py mul6x8.pr mul6x8.sound.json    # жду: функций 4, инструкций 54
python run_pr.py    mul6x8.pr                      # жду: value=48, steps=104
python run_sound.py mul6x8.sound.json --protocol mul6x8.sound.jsonl   # жду: 1064 записей
python mm_pred.py   inv_nonneg.mmx   mul6x8.sound.jsonl
python mm_pred.py   inv_pair.mmx     mul6x8.sound.jsonl
python mm_pred.py   inv_balance.mmx  mul6x8.sound.jsonl
