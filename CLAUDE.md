# Mina & Lisa 飲食紀錄

這個資料夾只做一件事：記錄兩隻母布偶貓 Mina 和 Lisa 的飲食（2026/06/07 生，吃皇家 K36 幼貓乾糧）。
回覆使用者一律用繁體中文、簡短。

## 檔案
- `飲食紀錄.md`：給使用者看的頁面，由 `feed.py` 自動產生，**不要手動編輯**。
- `data/feedings.csv`、`data/weights.csv`：原始資料。
- `feed.py`：記錄與計算工具；最上面的「設定」區塊放飼料熱量、預估成貓體重、每隻貓的調整係數。

## 記錄餵食
使用者說吃了多少克，就執行（每隻貓分開記）：

```bash
python3 feed.py add Mina 20
python3 feed.py add Lisa 18 --time 08:30
```

- 有說時間就加 `--time HH:MM`，有說日期（如「昨天」）就加 `--date YYYY-MM-DD`；沒說就用現在。
- 「兩隻各吃 20 克」→ 分別 add 兩次，各 20。
- 「兩隻一共吃了 40 克」→ `python3 feed.py add both 40`（平分成兩筆）。
- 「有剩」「吃很慢」之類的補充 → `--note`。
- 說的是「給了多少、剩多少」→ 記實際吃掉的克數，並在 `--note` 寫「給 20 剩 5」；說吃光就寫「給 20 吃光」。這樣才分得出是「給太少」還是「不想吃」，看到常吃光時提醒使用者可以多給。
- 名字不清楚、克數不確定時先問，不要猜。
- 不是 K36 的食物 → 加 `--food 代號`，例如汪喵星球純肉泥：`python3 feed.py add Mina 3 --food 肉泥`。
  代號和熱量在 `feed.py` 的 `FOODS`；出現新的食物就先加進 `FOODS`（查不到熱量就估計並註明，請使用者看包裝）。

執行後把腳本印出的「今天進度」轉述給使用者（每隻一行：已吃幾克/kcal、佔建議量幾 %、還可以吃多少）。

## 其他指令
- 體重：`python3 feed.py weight Lisa 2.7`（可加 `--date`）。建議熱量會自動用最新體重重算。
- 記錯了：`python3 feed.py undo`（刪最後一筆；`add both` 會產生兩筆，要 `undo 2`）。更早的錯誤就直接改 csv，再 `python3 feed.py render`。
- 只看進度：`python3 feed.py today`。

## 需要調整設定的時機（改 `feed.py` 上方的設定，然後 render）
- 使用者提供包裝上的「代謝能」數字 → 改 `FOOD_KCAL_PER_KG`。
- 結紮後、或獸醫給了新的份量 → 改該隻的 `factor`（例如 0.9），並提醒以獸醫建議為準。
- 已經超過一週沒有新的體重紀錄 → 回覆時順便提醒量體重。
- 滿 12 個月（2027/06/07）K36 不再適用 → 提醒換糧並重新評估建議量的算法。

## 自動 commit（使用者已同意，每次都做，不用再問）
每次 add / weight / undo / 改 csv / 改設定之後，立刻 commit 所有變動（`git add -A`）。
訊息用繁體中文寫清楚這次記了什麼，例如：
- `11/2 06:00 Mina 10g、Lisa 10g`
- `11/9 體重 Mina 2.8kg、Lisa 2.7kg`
- `刪除 11/2 14:16 Lisa 30g（記錯）`
- `K36 熱量改成包裝標示 4,000 kcal/kg`

訊息最後加上 `Co-Authored-By` 署名行。

## 自動 push 與合併回 main（使用者已同意，每次都做，不用再問）
commit 後立刻 push，並讓 main 同步到最新：
- 若在工作分支（如 `claude/...`）：`git push -u origin <分支>`，再 `git push origin HEAD:main`（fast-forward 合併回 main）。
- 若直接在 main 上：`git push origin main`。
- 若 main 有工作分支沒有的新 commit（無法 fast-forward）：先 `git fetch origin main && git rebase origin/main` 再 push；有衝突就停下來問使用者。
- 不要 force push。
