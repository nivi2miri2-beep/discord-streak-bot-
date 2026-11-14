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

# --- الأسئلة الأصلية القديمة ---
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

            if streak_lost or (result and diff_days > 1):
                cursor.execute("""
                    SELECT id, challenger_id, challenged_id FROM streak_duels 
                    WHERE (challenger_id = %s OR challenged_id = %s) AND status = 'active'
                """, (user_id, user_id))
                active_duels = cursor.fetchall()

                for duel_id, c_id, cd_id in active_duels:
                    winner_id = cd_id if c_id == user_id else c_id
                    loser_id = user_id
                    cursor.execute("UPDATE streak_duels SET status = 'finished' WHERE id = %s", (duel_id,))
                    conn.commit()

                    if CHALLENGE_CHANNEL_ID:
                        try:
                            channel = interaction.client.get_channel(CHALLENGE_CHANNEL_ID) or await interaction.client.fetch_channel(CHALLENGE_CHANNEL_ID)
                            if channel:
                                guild = interaction.guild
                                loser_member = guild.get_member(loser_id) or await interaction.client.fetch_user(loser_id)
                                winner_member = guild.get_member(winner_id) or await interaction.client.fetch_user(winner_id)
                                
                                loss_embed = discord.Embed(
                                    title="🚨 نهاية تحدي الستريك!",
                                    description=f"لقد سقط **{loser_member.display_name}** وخسر سلسلة التحدي أمام **{winner_member.display_name}** بعد أن تراجع في الستريك الخاص به! 💀",
                                    color=discord.Color.from_rgb(220, 20, 60)
                                )
                                loss_embed.set_image(url="https://media.giphy.com/media/yqGyGyGyNXzxlOIz2/giphy.gif")
                                await channel.send(content="@everyone", embed=loss_embed)
                        except Exception as ex:
                            print(f"Error sending duel loss: {ex}")

            cursor.close()
            conn.close()

            try:
                user = interaction.user
                if streak_lost:
                    dm_embed = discord.Embed(
                        title="أنباء حزينة..",
                        description="ضيعت عليك الستريك ياحلو ؟ فين راح حماسك ؟\nيله لا تستسلم وابدا سلسلة جديدة ولا تنساني لا ازعل منك",
                        color=discord.Color.from_rgb(200, 50, 50)
                    )
                    dm_embed.set_image(url="https://media.giphy.com/media/XOhNjDesPsfnS0GHz5/giphy.gif")
                    await user.send(embed=dm_embed)
                else:
                    success_gifs = [
                        "https://media.giphy.com/media/FYFWukbC5RA5KPCmjs/giphy.gif",
                        "https://media.giphy.com/media/jap5P8z66BvpgUDGak/giphy.gif",
                        "https://media.giphy.com/media/ekf5UulYRW9mZOpbmL/giphy.gif",
                        "https://media.giphy.com/media/uTyfvzWlczbNc7Mvdj/giphy.gif"
                    ]
                    dm_embed = discord.Embed(
                        title="أهلاً فيك، ★!!",
                        description="سجلت حضورك اليوم وصارت سلسلتك مستمرة.. كفو عليك وعلى هالتزام الحلو! (๑˃̵ᴗ˂̵)و ♡",
                        color=discord.Color.from_rgb(30, 30, 30)
                    )
                    dm_embed.set_image(url=random.choice(success_gifs))
                    await user.send(embed=dm_embed)
            except Exception as e:
                print(f"Could not send DM: {e}")

            public_embed = discord.Embed(
                title=f"سجل حضوره اليوم {display_name} ≛",
                description=f"{streak_status_text}\n\n"
                            f"إجاباتك الثلاث لليوم:\n"
                            f"١. ماذا فعلت من أجل التولبا اليوم؟\n"
                            f"٢. ما مستوى إيمانك اليوم؟\n"
                            f"٣. حكينا عن موقف صار اليوم؟\n\n"
                            f"تم توثيق الحضور بنجاح! ✨",
                color=discord.Color.from_rgb(35, 39, 42)
            )
            public_embed.add_field(name="١. ماذا فعلت من أجل التولبا اليوم؟", value=self.ans1.value, inline=False)
            public_embed.add_field(name="٢. ما مستوى إيمانك اليوم؟", value=self.ans2.value, inline=False)
            public_embed.add_field(name="٣. حكينا عن موقف صار اليوم؟", value=self.ans3.value, inline=False)

            await interaction.channel.send(embed=public_embed)
            await interaction.followup.send("✅ تم نشر إجاباتك وتحديث الستريك بنجاح!", ephemeral=True)

        except Exception as e:
            print(f"Error in modal submit: {e}")
            await interaction.followup.send("❌ حدث خطأ أثناء حفظ بيانات الحضور.", ephemeral=True)

class DuelResponseView(discord.ui.View):
    def __init__(self, challenger_id: int, challenged_id: int):
        super().__init__(timeout=300)
        self.challenger_id = challenger_id
        self.challenged_id = challenged_id

    @discord.ui.button(label="قبول التحدي ⚔️", style=discord.ButtonStyle.green)
    async def accept_duel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.challenged_id:
            await interaction.response.send_message("❌ هذا التحدي ليس موجهاً لك!", ephemeral=True)
            return
        await interaction.response.defer()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE streak_duels SET status = 'active' WHERE challenger_id = %s AND challenged_id = %s AND status = 'pending'",
            (self.challenger_id, self.challenged_id)
        )
        conn.commit()
        cursor.close()
        conn.close()
        for child in self.children:
            child.disabled = True
        await interaction.edit_original_response(content=f"⚔️ **قبل {interaction.user.display_name} التحدي!** المعركة على الستريك بدأت 🔥", view=self)

    @discord.ui.button(label="رفض ❌", style=discord.ButtonStyle.red)
    async def decline_duel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.challenged_id:
            await interaction.response.send_message("❌ هذا التحدي ليس موجهاً لك!", ephemeral=True)
            return
        await interaction.response.defer()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM streak_duels WHERE challenger_id = %s AND challenged_id = %s AND status = 'pending'",
            (self.challenger_id, self.challenged_id)
        )
        conn.commit()
        cursor.close()
        conn.close()
        for child in self.children:
            child.disabled = True
        await interaction.edit_original_response(content=f"❌ رفض {interaction.user.display_name} التحدي.", view=self)

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
        self.daily_reminder.start()
        print(f"Logged in as {self.user}")

    @tasks.loop(hours=24)
    async def daily_reminder(self):
        await self.wait_until_ready()
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        today_obj = datetime.strptime(today, '%Y-%m-%d').date()
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT user_id, streak_count, last_date FROM streaks WHERE streak_count > 0')
            users = cursor.fetchall()
            cursor.close()
            conn.close()

            for user_id, streak, last_date in users:
                last_date_obj = datetime.strptime(last_date, '%Y-%m-%d').date()
                if (today_obj - last_date_obj).days == 1:
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
                        print(f"Could not send reminder: {e}")
        except Exception as e:
            print(f"Error in background reminder: {e}")

client = StreakBot()
@client.tree.command(name="help", description="طريقة استخدام البوت وكيفية التعامل مع الأوامر")
async def help_cmd(interaction: discord.Interaction):
    help_embed = discord.Embed(
        title="📖 دليل استخدام بوت الاستمرارية والتولبا",
        description="مرحباً بك! هذا البوت مخصص لمساعدتك في تتبع انضباطك وسلسلتك اليومية:",
        color=discord.Color.from_rgb(88, 101, 242)
    )
    help_embed.add_field(name="📝 `/checkin`", value="لفتح نافذة الأسئلة اليومية وإجبارية الإجابة لتسجيل الحضور.", inline=False)
    help_embed.add_field(name="🔥 `/streak`", value="لعرض عدد أيام سلسلتك الحالية والاطلاع على تقدمك.", inline=False)
    help_embed.add_field(name="🏆 `/leaderboard`", value="لعرض لوحة الشرف (Top 10).", inline=False)
    help_embed.add_field(name="⚔️ `/streakduel @user`", value="لتحدي صديق في معركة الستريك.", inline=False)
    await interaction.response.send_message(embed=help_embed, ephemeral=True)

@client.tree.command(name="streakduel", description="تحدى صديقاً في معركة ستريك")
@app_commands.describe(member="الشخص الذي تريد تحديه")
async def streakduel_cmd(interaction: discord.Interaction, member: discord.Member):
    challenger = interaction.user
    if member.bot or member.id == challenger.id:
        await interaction.response.send_message("❌ لا يمكنك تحدي بوت أو نفسك!", ephemeral=True)
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM streak_duels 
        WHERE ((challenger_id = %s AND challenged_id = %s) OR (challenger_id = %s AND challenged_id = %s)) 
        AND status IN ('pending', 'active')
    """, (challenger.id, member.id, member.id, challenger.id))
    existing = cursor.fetchone()

    if existing:
        cursor.close()
        conn.close()
        await interaction.response.send_message("❌ يوجد تحدي قائم أو معلق بينكما بالفعل!", ephemeral=True)
        return

    cursor.execute(
        "INSERT INTO streak_duels (challenger_id, challenged_id, status) VALUES (%s, %s, %s)",
        (challenger.id, member.id, 'pending')
    )
    conn.commit()
    cursor.close()
    conn.close()

    view = DuelResponseView(challenger.id, member.id)
    await interaction.response.send_message(
        f"⚔️ **تحدي جديد في الستريك!**\n{member.mention}، لقد قام **{challenger.display_name}** بتحديك في معركة الستريك! هل تقبل التحدي؟",
        view=view
    )

@client.tree.command(name="checkin", description="افتح نافذة الأسئلة لتسجيل حضورك اليومي!")
async def checkin(interaction: discord.Interaction):
    user_id = interaction.user.id
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT last_date FROM streaks WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result and result[0] == today:
            await interaction.response.send_message("❌ لقد سجلت حضورك بالفعل، عد غدا لمواصلة سلسلة انتظامك.", ephemeral=True)
            return

        await interaction.response.send_modal(QuestionsModal())

    except Exception as e:
        print(f"Error checking checkin: {e}")
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
        print(f"Error in streak cmd: {e}")
        await interaction.response.send_message("❌ حدث خطأ أثناء جلب المعلومات.", ephemeral=True)

@client.tree.command(name="leaderboard", description="عرض لوحة الشرف وأكثر الأعضاء التزاماً (Top 10)")
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
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        print(f"Error in leaderboard: {e}")
        await interaction.response.send_message("❌ حدث خطأ أثناء تحميل لوحة الشرف.", ephemeral=True)

if __name__ == "__main__":
    keep_alive()
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        print("❌ Error: DISCORD_TOKEN environment variable not found!")
    else:
        client.run(TOKEN)
    
