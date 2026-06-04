import sqlite3
import random
import asyncio
import warnings
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Sarı renkli Python 3.12+ Deprecation uyarılarını gizler
warnings.filterwarnings("ignore", category=DeprecationWarning)

# --- 1. CONFIG VE YÖNETİCİ AYARLARI ---
DB_NAME = "casino_database.db"

# 🛑 YÖNETİCİ ID'LERİ VE BOT TOKENİ
ADMIN_IDS = [1282335065, 1553213587, 7244274042] 
TOKEN = "8711078496:AAEoGtgf7s2KIIaZarj7PU8YcCOgfqNAbLM"

# Bekleyen düelloları tutacağımız geçici bellek
active_duels = {}
active_games = {}

# --- 2. VERİTABANI AYARLARI ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0,
            last_bonus TEXT DEFAULT NULL
        )
    """)
    conn.commit()
    conn.close()

def get_balance(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row is None:
        cursor.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, ?)", (user_id, 0))
        conn.commit()
        balance = 0
    else:
        balance = row[0]
    conn.close()
    return balance

def update_balance(user_id, amount):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    current = get_balance(user_id)
    new_balance = max(0, current + amount)
    cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
    conn.commit()
    conn.close()
    return new_balance


# --- 3. OYUNCU KOMUTLARI VE OYUNLAR ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    balance = get_balance(user_id)
    
    welcome_text = (
        f"🎰 **Casino Botuna Hoş Geldin!** 🎰\n\n"
        f"💰 **Mevcut Bakiyen:** {balance} Çip\n"
        f"🆔 **Senin ID'n:** `{user_id}`\n\n"
        f"🎯 **Hızlı Oyun Menüsü**\n"
        f"• `/slot [Bahis]` -> Slot çevirir.\n"
        f"• `/atyarisi [At No] [Bahis]` -> At yarışı oynatır.\n"
        f"• `/rulet [Tahmin] [Bahis]` -> Rulet oynatır.\n"
        f"• `/duello [Bahis]` -> Başka bir oyuncunun mesajını yanıtlayarak ona meydan oku!\n\n"
        f"Tüm detaylar için **/komut** yazabilirsin!"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

# ⚔️ YENİ: OYUNCULAR ARASI ZAR DÜELLOSU
async def duello(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    thread_id = update.message.message_thread_id if update.message else None

    # Mesaj yanıtlanmış mı kontrolü
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ **Hatalı Kullanım!**\nBir oyuncuya düello teklif etmek için onun bir mesajını **yanıtlayarak** `/duello [Bahis]` yazmalısın.", message_thread_id=thread_id)
        return

    target_user = update.message.reply_to_message.from_user
    target_id = target_user.id

    if target_id == user_id:
        await update.message.reply_text("⚠️ Kendinle düello yapamazsın!", message_thread_id=thread_id)
        return
        
    if target_user.is_bot:
        await update.message.reply_text("⚠️ Botlarla düello yapamazsın! Kasa her zaman kazanır.", message_thread_id=thread_id)
        return

    if not context.args:
        await update.message.reply_text("⚠️ **Hatalı Kullanım!**\nBahis miktarını girmelisin. Örnek: `/duello 100`", message_thread_id=thread_id)
        return

    try:
        bet = int(context.args[0])
    except ValueError:
        await update.message.reply_text("⚠️ **Hata!** Bahis miktarı tam sayı olmalıdır.", message_thread_id=thread_id)
        return

    if bet <= 0:
        await update.message.reply_text("⚠️ Bahis 0'dan büyük olmalıdır.", message_thread_id=thread_id)
        return

    challenger_balance = get_balance(user_id)
    if challenger_balance < bet:
        await update.message.reply_text(f"❌ **Bakiyen yetersiz!** Bu düello için **{bet}** çipe ihtiyacın var. Sende olan: {challenger_balance}", message_thread_id=thread_id)
        return

    challenger_name = update.effective_user.first_name
    target_name = target_user.first_name

    # Teklifi belleğe kaydet
    active_duels[target_id] = {
        "challenger_id": user_id,
        "challenger_name": challenger_name,
        "target_name": target_name,
        "bet": bet
    }

    duello_text = (
        f"⚔️ **DÜELLO TEKLİFİ!** ⚔️\n\n"
        f"👤 **{challenger_name}**, {target_name} adlı oyuncuyu **{bet} Çip** karşılığında zar düellosuna davet etti!\n\n"
        f"👉 Kabul etmek için {target_name} adlı oyuncunun `/kabul` yazması gerekiyor."
    )
    await update.message.reply_text(duello_text, parse_mode="Markdown", message_thread_id=thread_id)

async def kabul(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_id = update.effective_user.id
    thread_id = update.message.message_thread_id if update.message else None

    # Bekleyen teklif var mı?
    if target_id not in active_duels:
        await update.message.reply_text("⚠️ Sana yapılmış bekleyen bir düello teklifi yok.", message_thread_id=thread_id)
        return

    duel_info = active_duels[target_id]
    challenger_id = duel_info["challenger_id"]
    bet = duel_info["bet"]
    challenger_name = duel_info["challenger_name"]
    target_name = duel_info["target_name"]

    # Bakiyeleri tekrar kontrol et (Kabul edene kadar paralarını harcamış olabilirler)
    target_balance = get_balance(target_id)
    if target_balance < bet:
        await update.message.reply_text(f"❌ **Bakiyen yetersiz!** Düelloyu kabul etmek için **{bet}** çipe ihtiyacın var.", message_thread_id=thread_id)
        return

    challenger_balance = get_balance(challenger_id)
    if challenger_balance < bet:
        await update.message.reply_text(f"❌ **İptal!** Teklifi yapan ({challenger_name}) oyuncusunun bakiyesi artık yetersiz. Düello iptal edildi.", message_thread_id=thread_id)
        del active_duels[target_id]
        return

    # İki taraftan da çipleri çek ve teklifi sil
    update_balance(target_id, -bet)
    update_balance(challenger_id, -bet)
    del active_duels[target_id]

    status_msg = await update.message.reply_text(f"⚔️ **DÜELLO BAŞLADI!** ⚔️\n\n💰 Masadaki Toplam Ödül: **{bet * 2} Çip**\n\n🎲 Zarlar fincanda sallanıyor...", message_thread_id=thread_id)
    await asyncio.sleep(1.5)

    # Kendi zar mantığımız (1 ile 6 arası)
    challenger_roll = random.randint(1, 6)
    target_roll = random.randint(1, 6)

    await status_msg.edit_text(f"🎲 **ZARLAR ATILIYOR...**\n\n👤 {challenger_name} zarı: **{challenger_roll}**\n👤 {target_name} zarı: **?**\n\nHeyecan dorukta...")
    await asyncio.sleep(1.5)

    if challenger_roll > target_roll:
        update_balance(challenger_id, bet * 2)
        result_text = f"🎉 **KAZANAN:** {challenger_name}!\n💰 **{bet * 2} Çip** kazandı!"
    elif target_roll > challenger_roll:
        update_balance(target_id, bet * 2)
        result_text = f"🎉 **KAZANAN:** {target_name}!\n💰 **{bet * 2} Çip** kazandı!"
    else:
        # Beraberlik durumunda paralar iade
        update_balance(challenger_id, bet)
        update_balance(target_id, bet)
        result_text = "🤝 **BERABERLİK!** İki tarafın da zarı aynı geldi. Bahisler iade edildi."

    final_msg = (
        f"🎲 **DÜELLO SONUCU** 🎲\n"
        f"-----------------------\n"
        f"👤 {challenger_name} ➔ **{challenger_roll}**\n"
        f"👤 {target_name} ➔ **{target_roll}**\n"
        f"-----------------------\n"
        f"{result_text}"
    )
    await status_msg.edit_text(final_msg, parse_mode="Markdown")

# 🛞 RULET OYUNU
async def play_roulette(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    thread_id = update.message.message_thread_id if update.message else None

    if not context.args or len(context.args) < 2:
        await update.message.reply_text("⚠️ **Hatalı Kullanım!**\nFormat: `/rulet [kirmizi/siyah veya Sayı(0-36)] [Bahis]`", message_thread_id=thread_id)
        return

    choice_str = context.args[0].lower()
    try:
        bet = int(context.args[1])
    except ValueError:
        await update.message.reply_text("⚠️ **Hata!** Bahis miktarı tam sayı olmalıdır.", message_thread_id=thread_id)
        return

    if bet <= 0:
        await update.message.reply_text("⚠️ **Geçersiz Bahis!** Bahis miktarı 0'dan büyük olmalıdır.", message_thread_id=thread_id)
        return

    bet_type = None 
    bet_value = None
    
    valid_colors = ['kirmizi', 'siyah', 'kırmızı']
    if choice_str in valid_colors:
        bet_type = 'color'
        bet_value = 'kirmizi' if choice_str in ['kirmizi', 'kırmızı'] else 'siyah'
    else:
        try:
            num = int(choice_str)
            if 0 <= num <= 36:
                bet_type = 'number'
                bet_value = num
            else:
                await update.message.reply_text("⚠️ **Geçersiz Sayı!** 0 ile 36 arasında bir sayı seçmelisin.", message_thread_id=thread_id)
                return
        except ValueError:
            await update.message.reply_text("⚠️ **Hatalı Bahis Türü!** Sadece 'kirmizi', 'siyah' veya 0-36 arası sayı girebilirsin.", message_thread_id=thread_id)
            return

    current_balance = get_balance(user_id)
    if current_balance < bet:
        await update.message.reply_text(f"❌ **Bakiyen yetersiz!** Bahis: **{bet}** Çip. Bakiyen: **{current_balance}** Çip.", message_thread_id=thread_id)
        return

    update_balance(user_id, -bet)

    status_msg = await update.message.reply_text("🛞 **Kurpiyer rulet çarkını çevirdi...** 🔴⚫", message_thread_id=thread_id)
    await asyncio.sleep(1.5)
    await status_msg.edit_text("🎲 **Top çarkta zıplıyor... Acaba nereye düşecek?** 🛞")
    await asyncio.sleep(1.5)

    result_num = random.randint(0, 36)
    red_numbers = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
    
    if result_num == 0:
        result_color = "yesil"
        color_emoji = "🟢"
    elif result_num in red_numbers:
        result_color = "kirmizi"
        color_emoji = "🔴"
    else:
        result_color = "siyah"
        color_emoji = "⚫"
    win = False
    multiplier = 0

    if bet_type == "color":
        if bet_value == result_color:
            win = True
            multiplier = 2

    elif bet_type == "number":
        if bet_value == result_num:
            win = True
            multiplier = 36

    if win:
        win_amount = bet * multiplier
        new_balance = update_balance(user_id, win_amount)

        result_text = (
            f"🎉 **KAZANDIN!**\n\n"
            f"Sonuç: {color_emoji} {result_num}\n"
            f"Ödül: **{win_amount} Çip**"
        )
    else:
        new_balance = get_balance(user_id)

        result_text = (
            f"😔 **Kaybettin!**\n\n"
            f"Sonuç: {color_emoji} {result_num}"
        )

    await status_msg.edit_text(
        f"{result_text}\n\n"
        f"💳 **Güncel Bakiyen:** {new_balance} Çip",
        parse_mode="Markdown"
    )

# 🎲 RİSK (YA HEP YA HİÇ) OYUNU
async def play_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    thread_id = update.message.message_thread_id if update.message else None

    if not context.args:
        await update.message.reply_text("⚠️ **Hatalı Kullanım!**\nFormat: `/risk [Bahis]`", message_thread_id=thread_id)
        return

    try:
        bet = int(context.args[0])
    except ValueError:
        return

    if bet <= 0:
        return

    current_balance = get_balance(user_id)
    if current_balance < bet:
        await update.message.reply_text(f"❌ **Bakiyen yetersiz!**", message_thread_id=thread_id)
        return

    update_balance(user_id, -bet)

    status_msg = await update.message.reply_text("🪙 **Yazı-Tura atılıyor...**", message_thread_id=thread_id)
    await asyncio.sleep(1.5)

    outcome = random.choice([0, 1])

    if outcome == 1:
        win_amount = bet * 2
        result_text = f"🟢 **KAZANDIN!**\nŞans senden yanaydı! Paranı tam **2 katına** çıkardın! 🎉"
    else:
        win_amount = 0
        result_text = f"🔴 **KAYBETTİN!**\nKader bu sefer yüzüne gülmedi..."

    new_balance = update_balance(user_id, win_amount)
    final_message = f"💀 **RİSK SİMÜLASYONU** 💀\n----------------------------------\n{result_text}\n\n💳 **Güncel Bakiyen:** {new_balance} Çip"
    await status_msg.edit_text(final_message, parse_mode="Markdown")

# 🏇 AT YARIŞI OYUNU
async def horse_race(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    thread_id = update.message.message_thread_id if update.message else None

    if not context.args or len(context.args) < 2:
        await update.message.reply_text("⚠️ **Hatalı Kullanım!**\nFormat: `/atyarisi [At Numarası] [Bahis]`", message_thread_id=thread_id)
        return

    try:
        chosen_horse = int(context.args[0])
        bet = int(context.args[1])
    except ValueError:
        return

    if chosen_horse < 1 or chosen_horse > 6 or bet <= 0:
        return

    current_balance = get_balance(user_id)
    if current_balance < bet:
        await update.message.reply_text(f"❌ **Bakiyen yetersiz!**", message_thread_id=thread_id)
        return

    update_balance(user_id, -bet)
    horses = {1: "🐎 At 1", 2: "🐎 At 2", 3: "🐎 At 3", 4: "🐎 At 4", 5: "🐎 At 5", 6: "🐎 At 6"}

    status_msg = await update.message.reply_text("🏁 **Yarış Başladı!**\n\n[🐎] [🐎] [🐎] [🐎] [🐎] [🐎] 💨", message_thread_id=thread_id)
    await asyncio.sleep(1.5)
    await status_msg.edit_text("🏃‍♂️ **Son düzlüğe giriliyor!**\n\n💨 [🐎]..[🐎]...[🐎]..[🐎]...[🐎]..[🐎]")
    await asyncio.sleep(1.5)

    winning_horse = random.randint(1, 6)

    if chosen_horse == winning_horse:
        win_amount = bet * 5
        result_text = f"🎉 **TEBRİKLER! Seçtiğin {horses[chosen_horse]} yarışı kazandı!** 🎉"
    else:
        win_amount = 0
        result_text = f"😔 **Maalesef kaybettin.** Kazanan: **{horses[winning_horse]}**"

    new_balance = update_balance(user_id, win_amount)
    final_message = f"🏇 **AT YARIŞI SONUÇLARI** 🏇\n----------------------------------\n{result_text}\n\n💳 **Güncel Bakiyen:** {new_balance} Çip"
    await status_msg.edit_text(final_message, parse_mode="Markdown")

# 🎰 SLOT OYUNU
async def play_slot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id if update.message else None

    bet = 50  
    if context.args:
        try:
            user_bet = int(context.args[0])
            if user_bet <= 0: return
            bet = user_bet
        except ValueError:
            return

    current_balance = get_balance(user_id)
    if current_balance < bet:
        await update.message.reply_text(f"❌ **Bakiyen yetersiz!**", message_thread_id=thread_id)
        return

    update_balance(user_id, -bet)
    
    slot_result = await context.bot.send_dice(chat_id=chat_id, emoji="🎰", message_thread_id=thread_id)
    dice_value = slot_result.dice.value

    win_amount = 0
    if dice_value == 1:
        win_amount = bet * 7
        result_text = f"🎉 **MUAZZAM! 7-7-7 GELDİ!** 🎉\n🔥 **Bahsinin 7 Katını Kazandın!**"
    elif dice_value in [22, 43, 64]:
        win_amount = bet * 5
        result_text = f"🔥 **HARİKA! 3'lü Kombinasyon Yakaladın!** 🔥\n💰 **Bahsinin 5 Katını Kazandın!**"
    else:
        win_amount = 0
        result_text = "😔 **Maalesef üçlemeyi yakalayamadın.**\nTekrar dene!"

    
    new_balance = update_balance(user_id, win_amount)
    final_message = f"{result_text}\n\n💳 **Güncel Bakiyen:** {new_balance} Çip"
    await update.message.reply_text(final_message, parse_mode="Markdown", message_thread_id=thread_id)

async def daily_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    thread_id = update.message.message_thread_id if update.message else None
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT last_bonus FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if row is None:
        get_balance(user_id)
        last_bonus_str = None
    else:
        last_bonus_str = row[0]
        
    now = datetime.now()
    
    if last_bonus_str:
        last_bonus_time = datetime.strptime(last_bonus_str, "%Y-%m-%d %H:%M:%S")
        if now < last_bonus_time + timedelta(days=1):
            remaining = (last_bonus_time + timedelta(days=1)) - now
            hours, remainder = divmod(remaining.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            await update.message.reply_text(f"❌ **Bonusunu zaten almışsın!**\nTekrar almak için `{hours} saat {minutes} dakika` beklemelisin.", parse_mode="Markdown", message_thread_id=thread_id)
            conn.close()
            return

    bonus_amount = random.randint(100, 500)
    cursor.execute("UPDATE users SET last_bonus = ? WHERE user_id = ?", (now.strftime("%Y-%m-%d %H:%M:%S"), user_id))
    conn.commit()
    conn.close()
    
    new_balance = update_balance(user_id, bonus_amount)
    await update.message.reply_text(f"🎁 **Günlük Bonus Alındı!**\n➕ Hesabınıza **{bonus_amount}** çip eklendi!\n💳 **Yeni Bakiyeniz:** {new_balance} Çip", parse_mode="Markdown", message_thread_id=thread_id)

async def top_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thread_id = update.message.message_thread_id if update.message else None
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT 10")
    rows = cursor.fetchall()
    conn.close()
    
    leaderboard = "🏆 **KUMARBAZLAR KRALLIĞI - TOP 10** 🏆\n\n"
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    for index, row in enumerate(rows):
        target_id = row[0]
        balance = row[1]
        leaderboard += f"{medals[index]} ID: `{target_id}` — 💰 **{balance} Çip**\n"
        
    await update.message.reply_text(leaderboard, parse_mode="Markdown", message_thread_id=thread_id)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    thread_id = update.message.message_thread_id if update.message else None
    
    help_text = (
        f"📖 **CASINO BOTU KOMUT LİSTESİ** 📖\n\n"
        f"🎮 **Oyunlar:**\n"
        f"• `/slot [Miktar]` - Belirttiğin miktarda slot çevirir\n"
        f"• `/atyarisi [At No] [Miktar]` - Seçtiğin ata bahis yatırır\n"
        f"• `/rulet [Tahmin] [Miktar]` - Rulet oynatır\n"
        f"• `/risk [Miktar]` - %50 şansla 2'ye katlar veya kaybeder\n"
        f"• `/duello [Miktar]` - Bir mesajı yanıtlayarak o kişiye düello teklif edersin\n"
        f"• `/kabul` - Sana gelen düello teklifini kabul edersin\n\n"
        f"🛠️ **Genel:**\n"
        f"• `/gunluk` - 24 saatte bir ücretsiz çip verir\n"
        f"• `/top10` - En zengin 10 oyuncuyu listeler\n"
    )
    
    if user_id in ADMIN_IDS:
        help_text += (
            f"\n⚡ **[ADMİN ÖZEL] Yönetim Komutları:**\n"
            f"• `/bakiyeekle [ID/Yanıt] [Miktar]`\n"
            f"• `/bakiyesil [ID/Yanıt] [Miktar]`\n"
            f"• `/panel` - Özet istatistikleri gösterir\n"
            f"• `/duyuru [Mesaj]` - Herkese özelden mesaj atar\n"
        )
        
    await update.message.reply_text(help_text, parse_mode="Markdown", message_thread_id=thread_id)


# --- 4. GÜVENLİ ADMİN KOMUTLARI ---

def get_target_and_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        target_id = update.message.reply_to_message.from_user.id
        try:
            amount = int(context.args[0]) if context.args else None
            return target_id, amount
        except ValueError:
            return None, None
    else:
        if not context.args or len(context.args) < 2:
            return None, None
        try:
            target_id = int(context.args[0])
            amount = int(context.args[1])
            return target_id, amount
        except ValueError:
            return None, None

async def add_balance_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    thread_id = update.message.message_thread_id if update.message else None
    target_id, amount = get_target_and_amount(update, context)
    if target_id is None or amount is None: return

    new_balance = update_balance(target_id, amount)
    await update.message.reply_text(f"✅ `{target_id}` ID'li kullanıcıya **{amount}** çip eklendi.", parse_mode="Markdown", message_thread_id=thread_id)

async def remove_balance_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    thread_id = update.message.message_thread_id if update.message else None
    target_id, amount = get_target_and_amount(update, context)
    if target_id is None or amount is None: return

    new_balance = update_balance(target_id, -amount)
    await update.message.reply_text(f"📉 `{target_id}` ID'li kullanıcıdan **{amount}** çip silindi.", parse_mode="Markdown", message_thread_id=thread_id)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    thread_id = update.message.message_thread_id if update.message else None
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(user_id), SUM(balance) FROM users")
    stats = cursor.fetchone()
    conn.close()
    
    panel_text = f"📊 **CASINO ADMİN PANELİ** 📊\n\n👥 Toplam Oyuncu: {stats[0] or 0}\n💰 Toplam Çip: {stats[1] or 0}"
    await update.message.reply_text(panel_text, parse_mode="Markdown", message_thread_id=thread_id)

async def broadcast_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    thread_id = update.message.message_thread_id if update.message else None
    if not context.args: return
        
    broadcast_msg = "📢 **ADMİN DUYURUSU** 📢\n\n" + " ".join(context.args)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()
    
    await update.message.reply_text(f"⏳ {len(users)} kişiye duyuru gönderiliyor...", message_thread_id=thread_id)
    basarili = 0
    for user in users:
        try:
            await context.bot.send_message(chat_id=user[0], text=broadcast_msg, parse_mode="Markdown")
            basarili += 1
        except Exception: pass
            
    await update.message.reply_text(f"✅ Tamamlandı! Ulaşılan: {basarili}/{len(users)}", message_thread_id=thread_id)


def calculate_hand(hand):
    score = 0
    aces = 0

    for card in hand:
        if card in ['J', 'Q', 'K']:
            score += 10
        elif card == 'A':
            score += 11
            aces += 1
        else:
            score += int(card)

    while score > 21 and aces:
        score -= 10
        aces -= 1

    return score


async def blackjack_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not context.args:
        await update.message.reply_text(
            "Kullanım:\n/blackjack [bahis]"
        )
        return

    try:
        bet = int(context.args[0])
    except ValueError:
        return

    if bet <= 0:
        return

    if get_balance(user_id) < bet:
        await update.message.reply_text("❌ Bakiyen yetersiz!")
        return

    update_balance(user_id, -bet)

    deck = [str(i) for i in range(2, 11)] + ['J', 'Q', 'K', 'A']

    player_hand = [
        random.choice(deck),
        random.choice(deck)
    ]

    dealer_hand = [
        random.choice(deck),
        random.choice(deck)
    ]

    active_games[user_id] = {
        "bet": bet,
        "player": player_hand,
        "dealer": dealer_hand
    }

    await update.message.reply_text(
        f"🃏 BLACKJACK\n\n"
        f"Sen: {player_hand}\n"
        f"Toplam: {calculate_hand(player_hand)}\n\n"
        f"Kasa: [{dealer_hand[0]}, ?]\n\n"
        f"/kart → Kart çek\n"
        f"/dur → Dur"
    )


async def blackjack_hit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in active_games:
        return

    deck = [str(i) for i in range(2, 11)] + ['J', 'Q', 'K', 'A']

    active_games[user_id]["player"].append(
        random.choice(deck)
    )

    score = calculate_hand(
        active_games[user_id]["player"]
    )

    if score > 21:
        await update.message.reply_text(
            f"💥 Bust!\nToplam: {score}\nKaybettin."
        )
        del active_games[user_id]
        return

    await update.message.reply_text(
        f"Yeni el:\n"
        f"{active_games[user_id]['player']}\n\n"
        f"Toplam: {score}"
    )


async def blackjack_stand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in active_games:
        return

    game = active_games[user_id]

    p_score = calculate_hand(game["player"])
    d_score = calculate_hand(game["dealer"])

    deck = [str(i) for i in range(2, 11)] + ['J', 'Q', 'K', 'A']

    while d_score < 17:
        game["dealer"].append(random.choice(deck))
        d_score = calculate_hand(game["dealer"])

    if d_score > 21 or p_score > d_score:
        update_balance(user_id, game["bet"] * 2)
        result = "🎉 Kazandın!"
    elif p_score < d_score:
        result = "😔 Kaybettin!"
    else:
        update_balance(user_id, game["bet"])
        result = "🤝 Berabere! Bahis iade edildi."

    await update.message.reply_text(
        f"Kasa Eli:\n"
        f"{game['dealer']}\n"
        f"Toplam: {d_score}\n\n"
        f"{result}"
    )

    del active_games[user_id]


async def bakiye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    balance = get_balance(update.effective_user.id)

    await update.message.reply_text(
        f"💰 Bakiyen: {balance} Çip"
    )


# --- 5. ANA ÇALIŞTIRICI ---
async def main():
    init_db()
    application = Application.builder().token(TOKEN).build()

    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass

    # Oyuncu Komutları
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("slot", play_slot))
    application.add_handler(CommandHandler("atyarisi", horse_race))
    application.add_handler(CommandHandler("risk", play_risk))
    application.add_handler(CommandHandler("rulet", play_roulette))
    application.add_handler(CommandHandler("duello", duello)) # Yeni Meydan Okuma
    application.add_handler(CommandHandler("kabul", kabul))   # Yeni Kabul Etme
    application.add_handler(CommandHandler("gunluk", daily_bonus))
    application.add_handler(CommandHandler("top10", top_players))
    application.add_handler(CommandHandler("komut", help_command))
    
    # Admin Komutları
    application.add_handler(CommandHandler("bakiyeekle", add_balance_admin))
    application.add_handler(CommandHandler("bakiyesil", remove_balance_admin))
    application.add_handler(CommandHandler("panel", admin_panel))
    application.add_handler(CommandHandler("duyuru", broadcast_admin))
    application.add_handler(CommandHandler("bakiye", bakiye))
    application.add_handler(CommandHandler("blackjack", blackjack_start))
    application.add_handler(CommandHandler("kart", blackjack_hit))
    application.add_handler(CommandHandler("dur", blackjack_stand))

    print("🎰 Bahis Ayarlı Casino Botu aktif... (Polling başlatılıyor)")
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except AttributeError:
        pass
        
    asyncio.run(main())