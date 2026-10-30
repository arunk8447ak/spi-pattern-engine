# V7.3 Auto – numbers apne aap Telegram par

## Ye kya karta hai
- **Result apne aap:** har shaam/raat result website se khud uthata hai aur `spi_results.json` mein bharta hai. Isliye dono laptop ke tool mein bhi dikh jaata hai.
- **Numbers apne aap (V7.3, plan `v7_plan.json` se):**
  - Faridabad ke baad → **Ghaziabad** ke 8 jodi (₹40)
  - Ghaziabad ke baad → **Gali** ke 7 jodi (MAIN chhod kar, ₹125) + BAHAR haruf (₹200) **aur** **Desawar** ke 8 jodi (₹75) + ANDAR haruf (₹150)
  - (V7.3 mein Desawar ko raat ke Gali result ki zaroorat nahi, isliye dono saath aate hain)
- **Subah:** Desawar ke baad kal ka hisaab (PASS/FAIL, ₹, 5% commission ke saath) aur is mahine ka total.
- **Bhaari-number prayog:** Gali se pehle khaiwale se "sabse bhaari 5 number" poochh kar bot ko reply karo: `bhaari 12 34 56 78 90`
  (Desawar ke liye `bhaari desawar 12 34 ...`). Subah ki report mein dikhega ki operator unhe bachata hai ya nahi.
- **Har saal 1 Jan:** bot model dobara train karke `v7_logic.json` likhta hai; tool aur bot dono naya logic khud utha lete hain.
- **Laptop on rakhna zaroori nahi.** Ye GitHub par chalta hai.

## Ek baar ka setup (phone se ~5 minute)
**Sabse aasaan:** phone par ye page kholo. Har step ka button wahan hai:
**https://arunk8447ak.github.io/spi-pattern-engine/setup.html** (portal par "Telegram Auto (V7.2)" card bhi yahi kholta hai).

Wahi steps yahan bhi:
1. **Timer file banao (GitHub):** setup page ka button "1. Timer file banao" dabao. GitHub par file pehle se bhari khulegi; bas **Commit changes** dabao.
   - Button kaam na kare to: [automation/workflow.yml](workflow.yml) kholo, poora text copy karo. Phir repo mein **Add file → Create new file**, naam `.github/workflows/v7_auto.yml` rakho, text paste karo aur commit karo.
   - (Ye step aapko khud karna padta hai, kyunki GitHub timer wali file sirf aap bana sakte ho.)
2. Telegram mein **@BotFather** kholo aur `/newbot` bhejo.
   - Koi bhi naam do, jaise `SPI V7`.
   - Phir username do jo `bot` par khatam ho, jaise `spi_v7_arun_bot`.
   - BotFather ek **token** dega (jaise `123456789:ABC...`). Ise copy kar lo.
   - Apne naye bot ko kholo aur **Start** dabao. Ye zaroori hai, warna bot aapko message nahi bhej sakta.
3. Telegram mein **@userinfobot** kholo aur Start dabao. Wo aapka **Id** (sirf number) dikhayega. Ise copy kar lo.
4. GitHub mein do secret daalo (phone browser mein "Desktop site" on karke, ya dusre laptop se):
   - Repo `arunk8447ak/spi-pattern-engine` kholo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.
   - Pehla secret: Name `TELEGRAM_BOT_TOKEN`, Secret mein step 2 wala token.
   - Dusra secret: Name `TELEGRAM_CHAT_ID`, Secret mein step 3 wala Id.
5. Test karo:
   - Repo ka **Actions** tab kholo → left mein **V7.2 Auto (results + Telegram)** chuno.
   - **Run workflow** dabao, mode `test` rehne do, phir hare **Run workflow** button par dabao.
   - 1–2 minute mein Telegram par "✅ V7.3 Auto chal raha hai!" aana chahiye.

## Roz ka kaam
- Har market ke liye 2 message aayenge. Pehle mein jaankari hogi. Doosra (sirf numbers wala) tap karke copy karo aur khaiwale ko bhej do.
- Website par result late ho to "⚠️" alert aayega. Tab tool khud khol kar dekh lo.

## Settings (`v7_plan.json`, repo root – tool aur bot dono yahi padhte hain)
| Setting | Matlab |
|---|---|
| `markets.<Market>.play` | Ye market khelna hai ya nahi |
| `markets.<Market>.skip_ranks` | V7 slate ke kaunse rank nahi khelne (1 = MAIN). Gali: [1] |
| `markets.<Market>.stake` | ₹ per jodi |
| `markets.<Market>.haruf` | `{"type": "bahar"/"andar", "stake": ₹}` ya `null` |
| `commission_pct`, `payout` | Hisaab ke liye (5, 90) |
| `heavy_experiment` | Gali message ke saath bhaari-number prayog ki line |

## Dhyan rahe
- GitHub ka timer kabhi-kabhi 5–15 minute late chalta hai.
- Ye purana result kabhi nahi badalta. Tool aur website mein fark dikhe to "Result check" message aata hai. Tab tool mein sahi result daal do.
- Agar 60 din tak repo mein koi badlaav na ho to GitHub timer band kar deta hai. Tab Actions tab mein **Enable workflow** dabana.
- Band karna ho to: Actions → V7.2 Auto → upar `...` → **Disable workflow**.
- Ye V7.2 ke pichhle data par based hai. Jeet ki koi guarantee nahi hai.
