import os
import logging
import re
import sys
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

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Environment variables - with validation
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = os.environ.get("ADMIN_ID")
OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "@dtxzahid")

# Validate required environment variables
if not BOT_TOKEN:
    logger.error("BOT_TOKEN environment variable is not set!")
    sys.exit(1)

if not ADMIN_ID:
    logger.error("ADMIN_ID environment variable is not set!")
    sys.exit(1)

try:
    ADMIN_ID = int(ADMIN_ID)
except ValueError:
    logger.error(f"ADMIN_ID must be a number! Got: {ADMIN_ID}")
    sys.exit(1)

# Conversation states
WAITING_FOR_IDS, WAITING_FOR_AMOUNT, WAITING_FOR_USER_ID = range(3)

# Store approvals in memory (will reset on restart)
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
    try:
        user = update.effective_user
        user_id = user.id
        
        logger.info(f"User {user_id} started the bot")
        
        # Check if user is admin
        if user_id == ADMIN_ID:
            await show_admin_menu(update, context)
            return
        
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
        
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🔔 New User Request:\n\n{user_info}\n\nStatus: ⏳ Pending",
            reply_markup=reply_markup
        )
        
        # Notify user
        await update.message.reply_text(
            "✅ Your request has been sent to the admin for approval.\n"
            "Please wait while your request is being reviewed."
        )
        
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await update.message.reply_text(
            "⚠️ An error occurred. Please try again later."
        )

async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show admin menu with special options"""
    keyboard = [
        [InlineKeyboardButton("📄 Payment Format", callback_data="payment_format")],
        [InlineKeyboardButton("📨 Message User by ID", callback_data="message_user")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.message.reply_text(
            "👑 Welcome Admin!\n\n"
            "Choose an option:",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "👑 Welcome Admin!\n\n"
            "Choose an option:",
            reply_markup=reply_markup
        )

async def handle_message_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start conversation to message user by ID"""
    try:
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        if user_id != ADMIN_ID:
            await query.edit_message_text("❌ This feature is for admin only!")
            return
        
        await query.edit_message_text(
            "📨 Send me the User ID you want to message:\n\n"
            "Example: `1234567890`",
            parse_mode='Markdown'
        )
        
        return WAITING_FOR_USER_ID
    except Exception as e:
        logger.error(f"Error in handle_message_user: {e}")
        return ConversationHandler.END

async def get_user_id_for_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get user ID and provide clickable link"""
    try:
        user_input = update.message.text.strip()
        
        # Check if it's a valid user ID
        if not user_input.isdigit() or len(user_input) < 5:
            await update.message.reply_text(
                "❌ Invalid User ID. Please send a valid numeric User ID (e.g., 1234567890):"
            )
            return WAITING_FOR_USER_ID
        
        user_id = int(user_input)
        
        # Create clickable link button
        keyboard = [[
            InlineKeyboardButton(
                f"📨 Message User {user_id}",
                url=f"tg://openmessage?user_id={user_id}"
            )
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"✅ User ID: `{user_id}`\n\n"
            "Click the button below to message this user directly:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        # Show admin menu again
        await show_admin_menu(update, context)
        
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in get_user_id_for_message: {e}")
        await update.message.reply_text(
            "⚠️ An error occurred. Please try again with /start"
        )
        return ConversationHandler.END

async def handle_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin approval/rejection"""
    try:
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
                f"```\n"
                f"User ID: {user_id}\n"
                f"Username: @{user_info.get('username', 'No username')}\n"
                f"Name: {user_info.get('first_name', '')} {user_info.get('last_name', '')}\n"
                f"```",
                parse_mode='Markdown'
            )
            
            # Notify user
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="🎉 Your request has been approved!\n\n"
                         "You can now use the bot. Use /start to begin."
                )
            except Exception as e:
                logger.warning(f"Could not notify user {user_id} about approval: {e}")
            
        elif action == "reject":
            # Notify admin
            user_info = pending_approvals.get(user_id, {})
            await query.edit_message_text(
                f"❌ User Rejected:\n\n"
                f"```\n"
                f"User ID: {user_id}\n"
                f"Username: @{user_info.get('username', 'No username')}\n"
                f"Name: {user_info.get('first_name', '')} {user_info.get('last_name', '')}\n"
                f"```",
                parse_mode='Markdown'
            )
            
            # Notify user
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="❌ Your request has been rejected.\n\n"
                         f"You aren't allowed to use this bot.\n"
                         f"Any queries? DM {OWNER_USERNAME}"
                )
            except Exception as e:
                logger.warning(f"Could not notify user {user_id} about rejection: {e}")
        
        # Remove from pending approvals
        pending_approvals.pop(user_id, None)
        
    except Exception as e:
        logger.error(f"Error in handle_approval: {e}")

async def show_payment_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show payment format option to user"""
    try:
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
    except Exception as e:
        logger.error(f"Error in show_payment_format: {e}")

async def handle_payment_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle payment format option"""
    try:
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
            "Please send your IDs now:",
            parse_mode='Markdown'
        )
        
        return WAITING_FOR_IDS
    except Exception as e:
        logger.error(f"Error in handle_payment_format: {e}")
        return ConversationHandler.END

async def process_user_ids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process user IDs and extract them - show in monospace"""
    try:
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
                "Please send IDs again:",
                parse_mode='Markdown'
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
        
        # Show extracted IDs line by line in monospace
        ids_formatted = '\n'.join(unique_ids)
        
        await update.message.reply_text(
            f"✅ Found {len(unique_ids)} unique user ID(s):\n\n"
            f"```\n{ids_formatted}\n```\n\n"
            "Now enter the amount to add (e.g., 2.1, 5, 10.5):",
            parse_mode='Markdown'
        )
        
        return WAITING_FOR_AMOUNT
    except Exception as e:
        logger.error(f"Error in process_user_ids: {e}")
        await update.message.reply_text(
            "⚠️ An error occurred. Please try again with /start"
        )
        return ConversationHandler.END

async def process_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process the amount and generate final output in monospace"""
    try:
        amount = update.message.text.strip()
        
        # Validate amount
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
        
        # Send the final formatted result in monospace
        await update.message.reply_text(
            "✅ Here's your formatted output:\n\n"
            f"```\n{final_output}\n```\n\n"
            "📋 **Easy to copy:** Just tap and hold on the text above, then select 'Copy'",
            parse_mode='Markdown'
        )
        
        # Clear user data
        context.user_data.clear()
        
        # Show appropriate menu based on user
        user_id = update.effective_user.id
        if user_id == ADMIN_ID:
            await show_admin_menu(update, context)
        else:
            keyboard = [[InlineKeyboardButton("📄 Format More IDs", callback_data="payment_format")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "Click below to format more IDs:",
                reply_markup=reply_markup
            )
        
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in process_amount: {e}")
        await update.message.reply_text(
            "⚠️ An error occurred. Please try again with /start"
        )
        return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the conversation"""
    try:
        context.user_data.clear()
        await update.message.reply_text(
            "❌ Operation cancelled.\n"
            "Use /start to begin again."
        )
    except Exception as e:
        logger.error(f"Error in cancel: {e}")
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a help message"""
    try:
        user_id = update.effective_user.id
        help_text = "🤖 Bot Commands:\n\n"
        
        if user_id == ADMIN_ID:
            help_text += (
                "👑 **Admin Commands:**\n"
                "/start - Show admin menu\n"
                "/help - Show this help message\n"
                "/cancel - Cancel current operation\n\n"
                "📋 **Admin Features:**\n"
                "1. Approve/Reject user requests\n"
                "2. Format payment IDs\n"
                "3. Message users by ID\n\n"
            )
        else:
            help_text += (
                "/start - Start the bot and request approval\n"
                "/help - Show this help message\n"
                "/cancel - Cancel current operation\n\n"
            )
        
        help_text += (
            f"For any queries, DM {OWNER_USERNAME}"
        )
        await update.message.reply_text(help_text)
    except Exception as e:
        logger.error(f"Error in help_command: {e}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors in the bot."""
    logger.error(f"Exception while handling an update: {context.error}")
    
    # You can add more specific error handling here
    try:
        if update and update.effective_user:
            await update.effective_user.send_message(
                "⚠️ An error occurred. Please try again later."
            )
    except:
        pass

def main():
    """Start the bot"""
    try:
        # Create the Application
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Add error handler
        application.add_error_handler(error_handler)
        
        # Add command handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("cancel", cancel))
        
        # Add callback query handler for admin approvals
        application.add_handler(CallbackQueryHandler(handle_approval, pattern=r'^(approve|reject)_\d+$'))
        
        # Add callback query handler for payment format option
        application.add_handler(CallbackQueryHandler(handle_payment_format, pattern=r'^payment_format$'))
        
        # Add callback query handler for message user option (admin only)
        application.add_handler(CallbackQueryHandler(handle_message_user, pattern=r'^message_user$'))
        
        # Create conversation handler for payment format
        payment_conv_handler = ConversationHandler(
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
        
        # Create conversation handler for messaging users
        message_conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(handle_message_user, pattern=r'^message_user$')],
            states={
                WAITING_FOR_USER_ID: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, get_user_id_for_message)
                ],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
            allow_reentry=True
        )
        
        application.add_handler(payment_conv_handler)
        application.add_handler(message_conv_handler)
        
        # Start the Bot
        logger.info("🤖 Bot is starting...")
        print("🤖 Bot is starting...")
        print(f"Admin ID: {ADMIN_ID}")
        print(f"Owner Username: {OWNER_USERNAME}")
        
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
        
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        print(f"❌ Failed to start bot: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
