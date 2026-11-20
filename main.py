import io
import os
import random
import asyncio
from datetime import datetime, timezone, timedelta
from threading import Thread

import discord
from discord import app_commands
from discord.ext import commands, tasks
from flask import Flask
import psycopg2
import requests

# --- Keep-Alive Web Server for Railway ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive and running!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

# --- Database Connection ---
def get_db_connection():
    db_url = os.getenv("DATABASE_URL")
    return psycopg2.connect(db_url)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS streaks (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            streak_count INTEGER DEFAULT 0,
            last_date TEXT,
            reminded_today BOOLEAN DEFAULT FALSE
        )
    ''')
    cursor.execute('''
        ALTER TABLE streaks
        ADD COLUMN IF NOT EXISTS reminded_today BOOLEAN DEFAULT FALSE
    ''')
    conn.commit()
    cursor.close()
    conn.close()


# --- Check-in Modal ---
class QuestionsModal(discord.ui.Modal, title='📝 تسجيل الحضور اليومي'):
    q1 = discord.ui.TextInput(
        label='كيف كان يومك وتقدمك اليوم؟',
        style=discord.TextStyle.paragraph,
        placeholder='اكتب ملخص بسيط عن إنجازك أو حالتك اليوم...',
        required=True,
        max_length=500
    )
    q2 = discord.ui.TextInput(
        label='ما هو هدفك الأساسي ليوم غد؟',
        style=discord.TextStyle.short,
        placeholder='هدف واحد واضح تلتزم به...',
        required=True,
        max_length=200
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        username = interaction.user.display_name
        now_utc = datetime.now(timezone.utc)
        today_str = now_utc.strftime('%Y-%m-%d')
        yesterday_str = (now_utc - timedelta(days=1)).strftime('%Y-%m-%d')

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT streak_count, last_date FROM streaks WHERE user_id = %s', (user_id,))
            row = cursor.fetchone()

            if row:
                current_streak, last_date = row
                if last_date == today_str:
                    cursor.close()
                    conn.close()
                    await interaction.followup.send("✅ لقد قمت بتسجيل حضورك لليوم بالفعل! نراك غداً 🔥", ephemeral=True)
                    return
                elif last_date == yesterday_str:
                    new_streak = current_streak + 1
                else:
                    new_streak = 1

                cursor.execute(
                    'UPDATE streaks SET streak_count = %s, last_date = %s, username = %s, reminded_today = FALSE WHERE user_id = %s',
                    (new_streak, today_str, username, user_id)
                )
            else:
                new_streak = 1
                cursor.execute(
                    'INSERT INTO streaks (user_id, username, streak_count, last_date, reminded_today) VALUES (%s, %s, %s, %s, FALSE)',
                    (user_id, username, new_streak, today_str)
                )

            conn.commit()
            cursor.close()
            conn.close()

            embed = discord.Embed(
                title="🔥 تم تسجيل حضورك بنجاح!",
                description=f"أحسنت يا **{username}**! سلسلتك الحالية وصلت إلى **{new_streak} يوم** من الالتزام المستمر. 🚀",
                color=discord.Color.from_rgb(88, 101, 242)
            )
            embed.add_field(name="📌 ملخص اليوم:", value=self.q1.value, inline=False)
            embed.add_field(name="🎯 هدف الغد:", value=self.q2.value, inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            print(f"Error in checkin modal: {e}")
            await interaction.followup.send("❌ حدث خطأ أثناء حفظ البيانات، يرجى المحاولة مرة أخرى.", ephemeral=True)

# --- Bot Setup & Background Tasks ---
class StreakBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        init_db()
        await self.tree.sync()
        self.check_streaks_task.start()

    async def on_ready(self):
        print(f"✅ Logged in as {self.user} (ID: {self.user.id})")

    @tasks.loop(hours=1)
    async def check_streaks_task(self):
        now_utc = datetime.now(timezone.utc)
        today_str = now_utc.strftime('%Y-%m-%d')
        yesterday_str = (now_utc - timedelta(days=1)).strftime('%Y-%m-%d')

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT user_id, streak_count, last_date, reminded_today FROM streaks WHERE streak_count > 0')
            users = cursor.fetchall()

            for user_id, streak_count, last_date, reminded_today in users:
                if last_date != today_str and last_date != yesterday_str:
                    cursor.execute('UPDATE streaks SET streak_count = 0, reminded_today = FALSE WHERE user_id = %s', (user_id,))
                    try:
                        user = await self.fetch_user(user_id)
                        await user.send(f"💔 للأسف ضاعت سلسلتك التي وصلت إلى **{streak_count} يوم** بسبب عدم تسجيل الحضور! لا تيأس، ابدأ من جديد اليوم باستخدام `/checkin` 💪")
                    except Exception:
                        pass
                elif last_date == yesterday_str and now_utc.hour >= 18 and not reminded_today:
                    cursor.execute('UPDATE streaks SET reminded_today = TRUE WHERE user_id = %s', (user_id,))
                    try:
                        user = await self.fetch_user(user_id)
                        await user.send(f"⏰ تذكير سريع! باقي ساعات قليلة وينتهي اليوم، لا تنسَ تسجيل حضورك بـ `/checkin` للحفاظ على سلسلتك (**{streak_count} يوم**) 🔥")
                    except Exception:
                        pass

            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"Error in check_streaks_task: {e}")

    @check_streaks_task.before_loop
    async def before_check_streaks(self):
        await self.wait_until_ready()

client = StreakBot()
    FORYOU_RAW_URL = "https://raw.githubusercontent.com/nivi2miri2-beep/discord-streak-bot-/refs/heads/main/foryou_messages.txt"
FORYOU_IMAGES_API_URL = "https://api.github.com/repos/nivi2miri2-beep/discord-streak-bot-/contents/foryou_images"
ALLOWED_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")

def get_random_foryou_message():
    try:
        response = requests.get(FORYOU_RAW_URL, timeout=10)
        response.raise_for_status()
        messages = [msg.strip() for msg in response.text.split("---") if msg.strip()]
        if not messages:
            return None
        return random.choice(messages)
    except Exception as e:
        print(f"Error fetching /foryou messages: {e}")
        return None

def get_random_foryou_image_file():
    try:
        response = requests.get(FORYOU_IMAGES_API_URL, timeout=10)
        response.raise_for_status()
        items = response.json()
        if not isinstance(items, list):
            return None, None

        image_items = [
            item
            for item in items
            if item.get("type") == "file"
            and item.get("name", "").lower().endswith(ALLOWED_IMAGE_EXTS)
            and item.get("download_url")
        ]
        if not image_items:
            return None, None

        chosen = random.choice(image_items)
        img_resp = requests.get(chosen["download_url"], timeout=15)
        img_resp.raise_for_status()

        filename = os.path.basename(chosen["name"])
        buffer = io.BytesIO(img_resp.content)
        buffer.seek(0)
        return discord.File(fp=buffer, filename=filename), filename
    except Exception as e:
        print(f"Error downloading /foryou image: {e}")
        return None, None

# --- أمر !info للوصف والتعريف بالبوت (باللهجة الخليجية المزوقة) ---
@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.content.strip().lower() == "!info":
        desc_embed = discord.Embed(
            title="✨ بـوت الإلـتـزام والـتـولـبـا 🌟",
            description="يا هلا بك يا راقي/يا راقية! 🌸 هذا رفيق دربك في السيرفر لمتابعة انضباطك، سلسلتك اليومية، ورحلتك بكل شغف واجتهاد. 💪🔥",
            color=discord.Color.from_rgb(88, 101, 242)
        )
        desc_embed.add_field(
            name="🔹 أهم الأوامر والخدمات:",
            value="* 📝 **`/checkin`** — سجّل حضورك اليومي وجاوب على الأسئلة، وخلك دائماً في القمة!\n"
                  "* 🔥 **`/streak`** — تشوّق واعرف كم يوم استمرت سلسلتك بوضوح (خاص فيك وحدك 🔒).\n"
                  "* 🏆 **`/leaderboard`** — ناظر لوحة الشرف وشوف الأبطال الملتزمين معنا في القمة (Top 10) 👑.\n"
                  "* 📖 **`/help`** — الدليل الشامل لكل أعضاء السيرفر عشان يستفيد الكل 🌟.\n"
                  "* ⚔️ **`/streakduel`** — تحدى صديق في معركة الستريك ⚔️.\n"
                  "* ✨ **`/foryou`** — رسالة مفاجأة عشوائية ليك!",
            inline=False
        )
        desc_embed.add_field(
            name="⏰ تذكير تلقائي:",
            value="لا تشيل هم نسيان الستريك! البوت يراقب وضعك ويرسل لك تنبيه في الخاص (DM) عشان ما يضيع تعبك وتطير سلسلتك 🚀.",
            inline=False
        )
        desc_embed.set_footer(text="✨ هات ما عندك، وخلنا نبني استمرارية تليق بطموحك! ☕🌿")

        await message.channel.send(embed=desc_embed)

    await client.process_commands(message)

# --- أمر الـ Freeze (يقرأ OWNER_ID من متغيرات البيئة بأمان) ---
@client.tree.command(name="freeze", description="تجميد ستريك عضو لحمايته من الضياع (خاص بمولات البوت)")
@app_commands.describe(member="العضو المراد تجميد ستريكه", days="عدد أيام التجميد")
async def freeze_cmd(interaction: discord.Interaction, member: discord.Member, days: int = 1):
    owner_id_env = os.getenv("OWNER_ID")

    if not owner_id_env or str(interaction.user.id) != str(owner_id_env):
        await interaction.response.send_message("❌ عذراً، هذا الأمر مخصص فقط لمولات البوت!", ephemeral=True)
        return

    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT streak_count FROM streaks WHERE user_id = %s', (member.id,))
        result = cursor.fetchone()

        if not result:
            cursor.close()
            conn.close()
            await interaction.response.send_message(f"❌ العضو {member.display_name} ليس لديه أي ستريك مسجل بعد!", ephemeral=True)
            return

        cursor.execute(
            'UPDATE streaks SET last_date = %s WHERE user_id = %s',
            (today, member.id)
        )
        conn.commit()
        cursor.close()
        conn.close()

        await interaction.response.send_message(
            f"❄️ تم تجميد وحماية ستريك العضو **{member.display_name}** بنجاح لمدة {days} يوم/أيام! لن يضيع ستريكه اليوم.",
            ephemeral=True
        )
    except Exception as e:
        print(f"Error in freeze command: {e}")
        await interaction.response.send_message("❌ حدث خطأ أثناء تنفيذ التجميد.", ephemeral=True)

@client.tree.command(name="foryou", description="رسالة مفاجأة عشوائية ليك!")
async def foryou_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    msg = get_random_foryou_message()

    if not msg:
        await interaction.followup.send("❌ ما قدرتش نجيب الرسائل دابا، عاود جرب شوية من بعد.", ephemeral=True)
        return

    discord_file, filename = get_random_foryou_image_file()

    embed = discord.Embed(
        title="✨ For You ✨",
        description=f"{interaction.user.mention}\n\n{msg}",
        color=discord.Color.from_rgb(255, 182, 193)
    )

    if discord_file and filename:
        embed.set_image(url=f"attachment://{filename}")
        await interaction.followup.send(embed=embed, file=discord_file)
    else:
        await interaction.followup.send(embed=embed)

@client.tree.command(name="help", description="طريقة استخدام البوت وكيفية التعامل مع الأوامر")
async def help_cmd(interaction: discord.Interaction):
    help_embed = discord.Embed(
        title="📖 دليل استخدام بوت الاستمرارية والتولبا",
        description="مرحباً بك! هذا البوت مخصص لمساعدتك في تتبع انضباطك وسلسلتك اليومية:",
        color=discord.Color.from_rgb(88, 101, 242)
    )
    help_embed.add_field(name="📝 `/checkin`", value="لفتح نافذة الأسئلة اليومية لتسجيل الحضور.", inline=False)
    help_embed.add_field(name="🔥 `/streak`", value="لعرض عدد أيام سلسلتك الحالية (خاص بك).", inline=False)
    help_embed.add_field(name="🏆 `/leaderboard`", value="لعرض لوحة الشرف (Top 10).", inline=False)
    help_embed.add_field(name="✨ `/foryou`", value="رسالة مفاجأة عشوائية ليك.", inline=False)
    await interaction.response.send_message(embed=help_embed, ephemeral=True)

@client.tree.command(name="checkin", description="افتح نافذة الأسئلة لتسجيل حضورك اليومي!")
async def checkin(interaction: discord.Interaction):
    await interaction.response.send_modal(QuestionsModal())

@client.tree.command(name="streak", description="اعرض عدد أيام سلسلتك الحالية في الانضباط!")
async def streak_cmd(interaction: discord.Interaction):
    user_id = interaction.user.id
    display_name = interaction.user.display_name

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT streak_count FROM streaks WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        desc = f"❌ ليس لديك أي سلسلة نشطة حالياً يا {display_name}. استخدم /checkin وابدأ رحلتك اليوم!" if (not result or result[0] == 0) else f"🔥 أهلاً بك يا {display_name}!\n\nانت في اليوم {result[0]} من سلسلة انضباطك واستمرارك."
        embed = discord.Embed(title=f"✨ تقرير السلسلة لـ {display_name}", description=desc, color=discord.Color.from_rgb(88, 101, 242))
        await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        print(f"Error: {e}")
        await interaction.response.send_message("❌ حدث خطأ أثناء جلب المعلومات.", ephemeral=True)

@client.tree.command(name="leaderboard", description="عرض لوحة الشرف وأكثر الأعضاء التزاماً")
async def leaderboard_cmd(interaction: discord.Interaction):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT username, streak_count FROM streaks WHERE streak_count > 0 ORDER BY streak_count DESC LIMIT 10')
        top_users = cursor.fetchall()
        cursor.close()
        conn.close()

        if not top_users:
            await interaction.response.send_message("❌ لا توجد أي بيانات مسجلة في لوحة الشرف حتى الآن!", ephemeral=True)
            return

        lb_description = "⚡ Top 10 • Consistency Leaderboard\n\n"
        medals = ["👑", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for index, (db_username, streak) in enumerate(top_users):
            medal = medals[index] if index < len(medals) else f"#{index+1}"
            lb_description += f"{medal} {db_username or 'Unknown'} — {streak} days 🔥\n"

        embed = discord.Embed(title="🏆 Server Leaderboard • Hall of Fame", description=lb_description, color=discord.Color.from_rgb(255, 215, 0))
        await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        print(f"Error: {e}")
        await interaction.response.send_message("❌ حدث خطأ أثناء تحميل لوحة الشرف.", ephemeral=True)

if __name__ == "__main__":
    keep_alive()
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        print("❌ Error: DISCORD_TOKEN environment variable not found!")
    else:
        client.run(TOKEN)
