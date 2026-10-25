# V7.2 Auto – numbers apne aap Telegram par

## Ye kya karta hai
- **Result apne aap:** har shaam/raat result website se khud uthata hai aur `spi_results.json` mein bharta hai. Isliye dono laptop ke tool mein bhi dikh jaata hai.
- **Numbers apne aap (V7.2):**
  - Faridabad ke baad → **Ghaziabad** ke 8 jodi
  - Ghaziabad ke baad → **Gali** ke 8 jodi + BAHAR haruf
  - Gali ke baad → **Desawar** ke 8 jodi
- **Subah:** Desawar ke baad kal ka hisaab (PASS/FAIL, ₹) aur is mahine ka total.
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
   - 1–2 minute mein Telegram par "✅ V7.2 Auto chal raha hai!" aana chahiye.

## Roz ka kaam
- Har market ke liye 2 message aayenge. Pehle mein jaankari hogi. Doosra (sirf numbers wala) tap karke copy karo aur khaiwale ko bhej do.
- Website par result late ho to "⚠️" alert aayega. Tab tool khud khol kar dekh lo.

## Settings (`automation/config.json`)
| Setting | Matlab |
|---|---|
| `markets` | Kin markets ke numbers bhejne hain (abhi Ghaziabad, Gali, Desawar) |
| `stake_per_jodi` | ₹ per jodi (abhi 75) |
| `gali_haruf_stake` | 0 = haruf sirf jaankari mein. 200 jaisa number = khaiwale wale message mein bhi haruf |
| `send_morning_report` | Subah ka hisaab bhejna hai ya nahi |

## Dhyan rahe
- GitHub ka timer kabhi-kabhi 5–15 minute late chalta hai.
- Ye purana result kabhi nahi badalta. Tool aur website mein fark dikhe to "Result check" message aata hai. Tab tool mein sahi result daal do.
- Agar 60 din tak repo mein koi badlaav na ho to GitHub timer band kar deta hai. Tab Actions tab mein **Enable workflow** dabana.
- Band karna ho to: Actions → V7.2 Auto → upar `...` → **Disable workflow**.
- Ye V7.2 ke pichhle data par based hai. Jeet ki koi guarantee nahi hai.
