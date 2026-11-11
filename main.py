import os
import discord
from discord import app_commands
from datetime import datetime, timezone, timedelta
from flask import Flask
from threading import Thread
import psycopg2  # الاتصال بقاعدة بيانات Neon PostgreSQL
import random
from discord.ext import tasks

# نظام الـ Web Server البسيط للحفاظ على التشغيل في Railway
app = Flask('')

@app.route('/')
def home():
    return "Bot is online and running on Railway! 🚀"

def run_web():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

def keep_alive():
    t = Thread(target=run_web)
    t.start()

# جلب رابط قاعدة البيانات من المتغيرات في Railway
DATABASE_URL = os.environ.get("DATABASE_URL")

# إعداد قاعدة البيانات في Neon (تضمن عدم ضياع الستريكات أبداً عند أي تحديث)
def init_neon_db():
    if not DATABASE_URL:
        print("❌ Error: DATABASE_URL is not set in environment variables!")
        return
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS streaks (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            streak_count INTEGER,
            last_date TEXT
        )
    """)
    conn.commit()
    cursor.close()
    conn.close()

# نافذة الأسئلة (Modal)
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
        label="٣. ما النتائج التي لاحظتها اليوم؟",
        style=discord.TextStyle.paragraph,
        placeholder="اكتب ملاحظاتك...",
        required=True,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        display_name = interaction.user.display_name

        answer_embed = discord.Embed(
            title=f"إجابات ≛ {display_name} لليوم",
            color=discord.Color.from_rgb(35, 39, 42)
        )
        answer_embed.add_field(name="ماذا فعلت من أجل التولبا اليوم؟", value=self.ans1.value, inline=False)
        answer_embed.add_field(name="ما مستوى إيمانك اليوم؟", value=self.ans2.value, inline=False)
        answer_embed.add_field(name="ما النتائج التي لاحظتها اليوم؟", value=self.ans3.value, inline=False)
        answer_embed.set_footer(text="شكراً لمشاركة تجربتك • لا تُحفظ هذه الإجابات في قاعدة البيانات")

        await interaction.channel.send(embed=answer_embed)
        await interaction.response.send_message("✅ تم نشر إجاباتك في الشات بنجاح!", ephemeral=True)

class CheckinView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="أجب عن أسئلة اليوم", style=discord.ButtonStyle.blurple, emoji="📝")
    async def answer_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(QuestionsModal())

class StreakBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        init_neon_db()
        await self.tree.sync()
        self.daily_reminder.start()
        print(f"Logged in as {self.user} (Connected to Neon DB)")

    # مهمة التذكير التلقائية في الخلفية
    @tasks.loop(hours=1)
    async def daily_reminder(self):
        await self.wait_until_ready()
        if not DATABASE_URL:
            return
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        today_obj = datetime.strptime(today, '%Y-%m-%d').date()

        try:
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor()
            cursor.execute('SELECT user_id, streak_count, last_date FROM streaks WHERE streak_count > 0')
            users = cursor.fetchall()
            cursor.close()
            conn.close()

            for user_id, streak, last_date in users:
                last_date_obj = datetime.strptime(last_date, '%Y-%m-%d').date()
                diff_days = (today_obj - last_date_obj).days

                if diff_days == 1:
                    try:
                        user = await self.fetch_user(user_id)
                        if user:
                            reminder_embed = discord.Embed(
                                title="⏰ تذكير السلسلة اليومية!",
                                description="مرحباً! لاحظت أنك لم تسجل حضورك اليوم بعد. سارع بعمل `/checkin` لكي لا تضيع سلسلتك المستمرة! 🔥",
                                color=discord.Color.from_rgb(255, 165, 0)
                            )
                            await user.send(embed=reminder_embed)
                    except Exception as e:
                        print(f"Could not send reminder to {user_id}: {e}")
        except Exception as e:
            print(f"Error in background reminder task: {e}")

client = StreakBot()

# --- أمر /help ---
@client.tree.command(name="help", description="طريقة استخدام البوت وكيفية التعامل مع الأوامر")
async def help_cmd(interaction: discord.Interaction):
    help_embed = discord.Embed(
        title="📖 دليل استخدام بوت الاستمرارية والتولبا",
        description="مرحباً بك! هذا البوت مخصص لمساعدتك في تتبع انضباطك وسلسلتك اليومية. إليك طريقة الاستخدام والأوامر المتوفرة:",
        color=discord.Color.from_rgb(88, 101, 242)
    )
    help_embed.add_field(
        name="📝 `/checkin`",
        value="لتسجيل حضورك اليومي عبر الإجابة على الأسئلة الثلاثة. سيصلك تقرير في الشات ورسالة خاصة (DM) مع الـ GIFs اللي اختاريتيها!",
        inline=False
    )
    help_embed.add_field(
        name="🔥 `/streak`",
        value="لعرض عدد أيام سلسلتك الحالية والاطلاع على تقدمك.",
        inline=False
    )
    help_embed.add_field(
        name="🏆 `/leaderboard`",
        value="لعرض لوحة الشرف (Top 10) لأكثر الأعضاء التزاماً في السيرفر.",
        inline=False
    )
    help_embed.add_field(
        name="⏰ نظام التذكير التلقائي",
        value="البوت يتفقد حالتك يومياً عبر Neon DB، وإذا اقتربت نهاية الوقت ولم تسجل حضورك، سيبعث لك تذكيراً في الخاص!",
        inline=False
    )
    help_embed.set_footer(text="نتمنى لك رحلة موفقة في تطوير انضباطك!")
    
    await interaction.response.send_message(embed=help_embed, ephemeral=True)

# --- أمر /checkin ---
@client.tree.command(name="checkin", description="سجل حضورك اليومي وبدأ أو واصل سلسلتك!")
async def checkin(interaction: discord.Interaction):
    if not DATABASE_URL:
        await interaction.response.send_message("❌ خطأ في الاتصال بقاعدة البيانات.", ephemeral=True)
        return

    user_id = interaction.user.id
    display_name = interaction.user.display_name
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute('SELECT streak_count, last_date FROM streaks WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()

        streak_status_text = ""
        streak_lost = False

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
                await interaction.response.send_message("❌ لقد سجلت حضورك بالفعل، عد غدا لمواصلة سلسلة انتظامك.", ephemeral=True)
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

        # إرسال الـ DM
        try:
            user = interaction.user
            if streak_lost:
                lost_gifs = [
                    "https://media.giphy.com/media/XOhNjDesPsfnS0GHz5/giphy.gif"
                ]
                chosen_lost_gif = random.choice(lost_gifs)

                dm_embed = discord.Embed(
                    title="أنباء حزينة..",
                    description="ضيعت عليك الستريك ياحلو ؟ فين راح حماسك ؟\nيله لا تستسلم وابدا سلسلة جديدة ولا تنساني لا ازعل منك",
                    color=discord.Color.from_rgb(200, 50, 50)
                )
                dm_embed.set_image(url=chosen_lost_gif)
                await user.send(embed=dm_embed)
            else:
                success_gifs = [
                    "https://media.giphy.com/media/FYFWukbC5RA5KPCmjs/giphy.gif",
                    "https://media.giphy.com/media/jap5P8z66BvpgUDGak/giphy.gif",
                    "https://media.giphy.com/media/ekf5UulYRW9mZOpbmL/giphy.gif",
                    "https://media.giphy.com/media/uTyfvzWlczbNc7Mvdj/giphy.gif",
                    "https://media.giphy.com/media/w36adguRoSl14L71YE/giphy.gif"
                ]
                chosen_gif = random.choice(success_gifs)

                dm_embed = discord.Embed(
                    title="أهلاً فيك، ★!!",
                    description="سجلت حضورك اليوم وصارت سلسلتك مستمرة.. كفو عليك وعلى هالتزام الحلو! (๑˃̵ᴗ˂̵)و ♡",
                    color=discord.Color.from_rgb(30, 30, 30)
                )
                dm_embed.set_image(url=chosen_gif)
                await user.send(embed=dm_embed)
                
        except Exception as e:
            print(f"Could not send DM: {e}")

        public_embed = discord.Embed(
            title=f"سجل حضوره اليوم {display_name} ≛",
            description=f"{streak_status_text}\n\n"
                        f"إجاباتك الثلاث لليوم\n"
                        f"١. ماذا فعلت من أجل التولبا اليوم؟\n"
                        f"٢. ما مستوى إيمانك اليوم؟\n"
                        f"٣. ما النتائج التي لاحظتها اليوم؟\n\n"
                        f"شارك فقط ما ترتاح لمشاركته علناً",
            color=discord.Color.from_rgb(35, 39, 42)
        )

        await interaction.response.send_message(embed=public_embed, view=CheckinView())

    except Exception as e:
        print(f"Error in checkin: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ حدث خطأ أثناء تسجيل الحضور، حاول لاحقاً.", ephemeral=True)

# --- أمر /streak ---
@client.tree.command(name="streak", description="اعرض عدد أيام سلسلتك الحالية في الانضباط!")
async def streak_cmd(interaction: discord.Interaction):
    if not DATABASE_URL:
        await interaction.response.send_message("❌ خطأ في الاتصال بقاعدة البيانات.", ephemeral=True)
        return

    user_id = interaction.user.id
    display_name = interaction.user.display_name

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute('SELECT streak_count FROM streaks WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result is None or result[0] == 0:
            desc = f"❌ ليس لديك أي سلسلة نشطة حالياً يا {display_name}. استخدم /checkin وابدأ رحلتك اليوم!"
        else:
            streak_count = result[0]
            desc = f"🔥 أهلاً بك يا {display_name}!\n\nانت في اليوم {streak_count} من سلسلة انضباطك واستمرارك."

        streak_embed = discord.Embed(
            title=f"✨ تقرير السلسلة لـ {display_name}",
            description=desc,
            color=discord.Color.from_rgb(88, 101, 242)
        )
        await interaction.response.send_message(embed=streak_embed, ephemeral=True)
    except Exception as e:
        print(f"Error in streak command: {e}")
        await interaction.response.send_message("❌ حدث خطأ أثناء جلب المعلومات.", ephemeral=True)

# --- أمر /leaderboard ---
@client.tree.command(name="leaderboard", description="عرض لوحة الشرف وأكثر الأعضاء التزاماً (Top 10)")
async def leaderboard_cmd(interaction: discord.Interaction):
    if not DATABASE_URL:
        await interaction.response.send_message("❌ خطأ في الاتصال بقاعدة البيانات.", ephemeral=True)
        return

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, username, streak_count FROM streaks WHERE streak_count > 0 ORDER BY streak_count DESC LIMIT 10')
        top_users = cursor.fetchall()
        cursor.close()
        conn.close()

        if not top_users:
            await interaction.response.send_message("❌ لا توجد أي بيانات مسجلة في لوحة الشرف حتى الآن!", ephemeral=True)
            return

        lb_description = "⚡ Top 10 • Consistency Leaderboard\n\n"
        medals = ["👑", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

        for index, (user_id, db_username, streak) in enumerate(top_users):
            medal = medals[index] if index < len(medals) else f"#{index+1}"
            current_name = db_username or "Unknown"
            lb_description += f"{medal} {current_name} — {streak} days 🔥\n"

        lb_embed = discord.Embed(
            title="🏆 Server Leaderboard • Hall of Fame",
            description=lb_description,
            color=discord.Color.from_rgb(255, 215, 0)
        )
        await interaction.response.send_message(embed=lb_embed)
    except Exception as e:
        print(f"Error in leaderboard: {e}")
        await interaction.response.send_message("❌ حدث خطأ أثناء تحميل لوحة الشرف.", ephemeral=True)

if __name__ == "__main__":
    keep_alive()
    TOKEN = os.environ.get("DISCORD_TOKEN")
    if not TOKEN:
        print("❌ Error: DISCORD_TOKEN is not set in environment variables!")
    else:
        client.run(TOKEN)
