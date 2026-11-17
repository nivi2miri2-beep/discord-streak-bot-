import os
import discord
from discord import app_commands
from datetime import datetime, timezone
from flask import Flask
from threading import Thread
import psycopg2
import random
from discord.ext import tasks
from urllib.parse import urlparse

CHALLENGE_CHANNEL_ID = 1479578382252511383

app = Flask('')

@app.route('/')
def home():
    return "Bot is online and running with PostgreSQL! 🚀"

def run_web():
    app.run(host='0.0.0.0', port=8080)

keep_alive = lambda: Thread(target=run_web).start()

def get_db_connection():
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        url = urlparse(database_url)
        return psycopg2.connect(
            database=url.path[1:],
            user=url.username,
            password=url.password,
            host=url.hostname,
            port=url.port
        )
    else:
        return psycopg2.connect(database_url)

def init_postgres_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS streaks (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                streak_count INTEGER,
                last_date TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS streak_duels (
                id SERIAL PRIMARY KEY,
                challenger_id BIGINT,
                challenged_id BIGINT,
                status TEXT
            )
        """)
        conn.commit()
        cursor.close()
        conn.close()
        print("✅ PostgreSQL Database tables initialized successfully.")
    except Exception as e:
        print(f"❌ Error initializing database: {e}")

class QuestionsModal(discord.ui.Modal, title="أسئلة الحضور اليومية"):
    ans1 = discord.ui.TextInput(
        label="١. ماذا فعلت من أجل التولبا اليوم؟",
        style=discord.TextStyle.paragraph,
        placeholder="اكتب إجابتك هنا...",
        required=True,
        max_length=1000
    )
    ans2 = discord.ui.TextInput(
        label="٢. ما مستوى إيمانك اليوم؟",
        style=discord.TextStyle.short,
        placeholder="اكتب مستواك...",
        required=True,
        max_length=200
    )
    ans3 = discord.ui.TextInput(
        label=" ٣.حكينا عن موقف صار اليوم ",
        style=discord.TextStyle.paragraph,
        placeholder="اكتب ملاحظاتك...",
        required=True,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        display_name = interaction.user.display_name
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT streak_count, last_date FROM streaks WHERE user_id = %s', (user_id,))
            result = cursor.fetchone()

            streak_status_text = ""
            streak_lost = False
            diff_days = 0

            if result is None:
                cursor.execute(
                    'INSERT INTO streaks (user_id, username, streak_count, last_date) VALUES (%s, %s, %s, %s)',
                    (user_id, display_name, 1, today)
                )
                streak_count = 1
                streak_status_text = "اليوم الأول — بداية رحلتك\n\n· سلسلة تبدأ بخطوة. بدأت رحلتك اليوم في اليوم الأول؛ عد غداً لمواصلتها."
            else:
                streak_count, last_date = result
                last_date_obj = datetime.strptime(last_date, '%Y-%m-%d').date()
                today_obj = datetime.strptime(today, '%Y-%m-%d').date()
                diff_days = (today_obj - last_date_obj).days

                if diff_days == 0:
                    cursor.close()
                    conn.close()
                    await interaction.followup.send("❌ لقد سجلت حضورك وأجبت عن الأسئلة مسبقاً اليوم!", ephemeral=True)
                    return
                elif diff_days == 1:
                    streak_count += 1
                    cursor.execute(
                        'UPDATE streaks SET streak_count = %s, username = %s, last_date = %s WHERE user_id = %s',
                        (streak_count, display_name, today, user_id)
                    )
                    streak_status_text = f"سلسلة متواصلة — {streak_count} يوماً!\n\nأحسنت بالعودة اليوم! أنت تبني الاستمرارية خطوة بعد خطوة."
                else:
                    streak_lost = True
                    streak_count = 1
                    cursor.execute(
                        'UPDATE streaks SET streak_count = %s, username = %s, last_date = %s WHERE user_id = %s',
                        (1, display_name, today, user_id)
                    )
                    streak_status_text = f"بداية جديدة — اليوم الأول\n\nانتهت سلسلتك السابقة وتم تصفير السترنك. حضورك اليوم يبدأ سلسلة جديدة."

            conn.commit()
            cursor.close()
            conn.close()

            public_embed = discord.Embed(
                title=f"سجل حضوره اليوم {display_name} ≛",
                description=f"{streak_status_text}\n\nتم توثيق الحضور بنجاح! ✨",
                color=discord.Color.from_rgb(35, 39, 42)
            )
            await interaction.channel.send(embed=public_embed)
            await interaction.followup.send("✅ تم تحديث الستريك بنجاح!", ephemeral=True)

        except Exception as e:
            print(f"Error: {e}")
            await interaction.followup.send("❌ حدث خطأ.", ephemeral=True)

class StreakBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        init_postgres_db()
        await self.tree.sync()
        print(f"Logged in as {self.user}")

client = StreakBot()
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
            value="* 📝 **`/checkin`** — سجّل حضورك اليومي وجاوب على الأسئلة\n"
                  "* 🔥 **`/streak`** — عرض تقرير سلسلتك الخاص 🔒\n"
                  "* 🏆 **`/leaderboard`** — لوحة الشرف (Top 10) 👑\n"
                  "* ⚔️ **`/streakduel`** — تحدي صديق في معركة الستريك ⚔️",
            inline=False
        )
        await message.channel.send(embed=desc_embed)

# --- أمر الـ Freeze (يقرأ OWNER_ID من متغيرات البيئة بأمان) ---
@client.tree.command(name="freeze", description="تجميد ستريك عضو لحمايته من الضياع (خاص بمولات البوت)")
@app_commands.describe(member="العضو المراد تجميد ستريكه", days="عدد أيام التجميد")
async def freeze_cmd(interaction: discord.Interaction, member: discord.Member, days: int = 1):
    owner_id_env = os.getenv("OWNER_ID")
    
    # التأكد من مطابقة الآيدي أو رفض الطلب
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
