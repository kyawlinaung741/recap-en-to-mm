

## Myanmar Subtitle (Voice-synced)

Recap render ပြီးတဲ့အခါ `smart_sync_plan_edge_tts.json` ထဲက TTS timing (`audio_start` / `audio_end`) ကို master clock အဖြစ်သုံးပြီး `edge_tts_smart_sync/subtitles_myanmar.srt` ကို အလိုအလျောက် ထုတ်ပေးပါတယ်။ ထို့ကြောင့် Subtitle က မူရင်း video timestamp မဟုတ်ဘဲ မြန်မာအသံနဲ့ တစ်ထပ်တည်း ပေါ်ပါတယ်။

ညာဘက် **Production Tools → Myanmar Subtitles (voice-synced)** မှာ:

- **Burn subtitles into final MP4** — Subtitle ကို video ထဲ တစ်ခါတည်းထည့်ရန် ဖွင့်/ပိတ်နိုင်ပါတယ်။
- **Location** — Top / Middle / Bottom နှင့် Left / Center / Right ကို ရွေးနိုင်ပါတယ်။
- **Font size** — Subtitle စာလုံးအရွယ်ကို 10–96 အတွင်း ပြင်နိုင်ပါတယ်။
- **Margin** — Video အနားကွာဟမှုကို ပြင်နိုင်ပါတယ်။

SRT ဖိုင်ကို သီးခြားသုံးလိုပါက `jobs\\<video>_<code>\\edge_tts_smart_sync\\subtitles_myanmar.srt` မှာ ရှိပါတယ်။ Burn-in ဖွင့်ထားရင် Output MP4 အသစ်ထဲမှာ Subtitle ပါပြီးသားဖြစ်ပါတယ်။
