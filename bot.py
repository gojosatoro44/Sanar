import os
import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes
)

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))  # Your Telegram user ID
OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "@dtxzahid")

# Conversation states
WAITING_FOR_IDS, WAITING_FOR_AMOUNT = range(2)

# Store approvals
pending_approvals = {}
approved_users = set()

class UserManager:
    """Manage user approvals"""
    
    @staticmethod
    def get_user_info(user_id: int, username: str, first_name: str, last_name: str = "") -> str:
        return f"""🆔 User ID: {user_id}
👤 Username: @{username if username else 'No username'}
📛 Name: {first_name} {last_name if last_name else ''}"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    user = update.effective_user
    user_id = user.id
    
    # Check if user is already approved
    if user_id in approved_users:
        await show_payment_format(update, context)
        return
    
    # Store user info for approval
    pending_approvals[user_id] = {
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name or ''
    }
    
    # Create approval message for admin
    user_info = UserManager.get_user_info(
        user_id, 
        user.username or "No username", 
        user.first_name, 
        user.last_name or ""
    )
    
    # Send to admin
    keyboard = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🔔 New User Request:\n\n{user_info}\n\nStatus: ⏳ Pending",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Failed to send approval request to admin: {e}")
        await update.message.reply_text("⚠️ Bot owner configuration error. Please contact the admin.")
        return
    
    # Notify user
    await update.message.reply_text(
        "✅ Your request has been sent to the admin for approval.\n"
        "Please wait while your request is being reviewed."
    )

async def handle_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin approval/rejection"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    action, user_id = data.split("_")
    user_id = int(user_id)
    
    if action == "approve":
        # Add to approved users
        approved_users.add(user_id)
        
        # Notify admin
        user_info = pending_approvals.get(user_id, {})
        await query.edit_message_text(
            f"✅ User Approved:\n\n"
            f"User ID: {user_id}\n"
            f"Username: @{user_info.get('username', 'No username')}\n"
            f"Name: {user_info.get('first_name', '')} {user_info.get('last_name', '')}",
            reply_markup=None
        )
        
        # Notify user
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="🎉 Your request has been approved!\n\n"
                     "You can now use the bot. Use /start to begin."
            )
        except:
            logger.warning(f"Could not notify user {user_id} about approval")
        
    elif action == "reject":
        # Notify admin
        user_info = pending_approvals.get(user_id, {})
        await query.edit_message_text(
            f"❌ User Rejected:\n\n"
            f"User ID: {user_id}\n"
            f"Username: @{user_info.get('username', 'No username')}\n"
            f"Name: {user_info.get('first_name', '')} {user_info.get('last_name', '')}",
            reply_markup=None
        )
        
        # Notify user
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ Your request has been rejected.\n\n"
                     f"You aren't allowed to use this bot.\n"
                     f"Any queries? DM {OWNER_USERNAME}"
            )
        except:
            logger.warning(f"Could not notify user {user_id} about rejection")
    
    # Remove from pending approvals
    pending_approvals.pop(user_id, None)

async def show_payment_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show payment format option to user"""
    keyboard = [[InlineKeyboardButton("📄 Payment Format", callback_data="payment_format")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.message.reply_text(
            "👋 Welcome to the bot!\n\n"
            "Click the button below to format user IDs:",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "👋 Welcome to the bot!\n\n"
            "Click the button below to format user IDs:",
            reply_markup=reply_markup
        )

async def handle_payment_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle payment format option"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📝 Send me the user IDs in any format.\n\n"
        "I will extract all user IDs and format them.\n\n"
        "Example input:\n"
        "```\n"
        "6486714430 Got Invited By Your Url: +3 Rs\n"
        "7944746107 Got Invited By Your Url: +3 Rs\n"
        "7891172965 Got Invited By Your Url: +3 Rs\n"
        "```\n\n"
        "First I'll show you extracted IDs, then ask for amount.\n"
        "Finally, I'll give you formatted output:\n"
        "```\n"
        "6486714430 2.1\n"
        "7944746107 2.1\n"
        "7891172965 2.1\n"
        "```\n\n"
        "Please send your IDs now:"
    )
    
    return WAITING_FOR_IDS

async def process_user_ids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process user IDs and extract them"""
    message_text = update.message.text
    
    # Extract user IDs - looking for sequences of digits (5 or more digits)
    user_ids = re.findall(r'\b\d{5,}\b', message_text)
    
    if not user_ids:
        await update.message.reply_text(
            "❌ No user IDs found in your message.\n\n"
            "Please make sure you're sending user IDs in the format:\n"
            "```\n"
            "6486714430 Got Invited By Your Url: +3 Rs\n"
            "7944746107 Got Invited By Your Url: +3 Rs\n"
            "```\n\n"
            "Or simply send numbers like:\n"
            "```\n"
            "6486714430\n"
            "7944746107\n"
            "7891172965\n"
            "```\n\n"
            "Please send IDs again:"
        )
        return WAITING_FOR_IDS
    
    # Remove duplicates while preserving order
    unique_ids = []
    seen = set()
    for uid in user_ids:
        if uid not in seen:
            seen.add(uid)
            unique_ids.append(uid)
    
    # Store in context
    context.user_data['user_ids'] = unique_ids
    
    # Show extracted IDs line by line
    ids_formatted = '\n'.join(unique_ids)
    
    await update.message.reply_text(
        f"✅ Found {len(unique_ids)} unique user ID(s):\n\n"
        f"```\n{ids_formatted}\n```\n\n"
        "Now enter the amount to add (e.g., 2.1, 5, 10.5):",
        parse_mode='Markdown'
    )
    
    return WAITING_FOR_AMOUNT

async def process_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process the amount and generate final output"""
    amount = update.message.text.strip()
    
    # Validate amount (simple validation - can be number or string)
    if not amount:
        await update.message.reply_text(
            "❌ Please enter a valid amount (e.g., 2.1, 5, 10.5):"
        )
        return WAITING_FOR_AMOUNT
    
    user_ids = context.user_data.get('user_ids', [])
    
    if not user_ids:
        await update.message.reply_text(
            "❌ No user IDs found. Please start over with /start"
        )
        return ConversationHandler.END
    
    # Create final formatted output
    formatted_lines = []
    for user_id in user_ids:
        formatted_lines.append(f"{user_id} {amount}")
    
    final_output = '\n'.join(formatted_lines)
    
    # Send the final formatted result
    await update.message.reply_text(
        "✅ Here's your formatted output:\n\n"
        f"```\n{final_output}\n```\n\n"
        "Use /start to format more IDs.",
        parse_mode='Markdown'
    )
    
    # Clear user data
    context.user_data.clear()
    
    # Show button to format more
    keyboard = [[InlineKeyboardButton("📄 Format More IDs", callback_data="payment_format")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Click below to format more IDs:",
        reply_markup=reply_markup
    )
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the conversation"""
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Operation cancelled.\n"
        "Use /start to begin again."
    )
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a help message"""
    help_text = (
        "🤖 Bot Commands:\n\n"
        "/start - Start the bot and request approval\n"
        "/help - Show this help message\n"
        "/cancel - Cancel current operation\n\n"
        "📋 How to use:\n"
        "1. Send /start to request approval\n"
        "2. Once approved, click 'Payment Format'\n"
        "3. Send user IDs in any format\n"
        "4. I'll show extracted IDs line by line\n"
        "5. Enter the amount\n"
        "6. Get formatted output: id amount\n\n"
        f"For any queries, DM {OWNER_USERNAME}"
    )
    await update.message.reply_text(help_text)

def main():
    """Start the bot"""
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cancel", cancel))
    
    # Add callback query handler for admin approvals
    application.add_handler(CallbackQueryHandler(handle_approval, pattern=r'^(approve|reject)_\d+$'))
    
    # Create conversation handler for payment format
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_payment_format, pattern=r'^payment_format$')],
        states={
            WAITING_FOR_IDS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_user_ids)
            ],
            WAITING_FOR_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_amount)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )
    
    application.add_handler(conv_handler)
    
    # Start the Bot
    print("🤖 Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
