"""Stage-appropriate copy-paste email templates for client inquiries (P-037 Ph-3).

"label" is UI chrome (the template picker), translated via gettext_lazy; subject/body
are authored email content, not Django-i18n UI text — same exemption as
utils/email_utils.py.
"""

from typing import Any

from django.utils.translation import gettext_lazy

from ..models import InquiryStatus

STAGE_EMAIL_TEMPLATES: dict[str, dict[str, Any]] = {
    InquiryStatus.NEW: {
        "label": gettext_lazy("Acknowledge receipt"),
        "subject": "Your inquiry — Thank you for reaching out",
        "body": (
            "Hi <..>,\n\n"
            "Thank you for your message. I would love to arrange a time for a brief "
            "introductory meeting to learn more about what brings you here. We can "
            "also explore together what might be helpful for you going forward.\n\n"
            "Would you have time for an informal get-to-know (approx. 20 minutes, "
            "via video call or phone)? To book a time, please choose 'intro call' on "
            "[booking URL] and pick a time. "
            "And if you don't wish to create an account, that's fine — feel free to "
            "just email back a time that would suit you for an introductory call.\n\n"
            "Warm regards and all the best,\n"
            "[Your name]"
        ),
    },
    InquiryStatus.CONTACTED: {
        "label": gettext_lazy("Propose intro meeting"),
        "subject": "Scheduling a brief introductory call",
        "body": (
            "Hello,\n\n"
            "Thank you for your message. I would be glad to set up a brief "
            "introductory call so we can talk about what might be helpful for you.\n\n"
            "Would you have time for a short, no-obligation conversation "
            "(approx. 20 minutes, via video call or phone)? "
            "Here are a few times I can offer:\n"
            "– [Time 1]\n"
            "– [Time 2]\n\n"
            "Best regards,\n"
            "[Your name]"
        ),
    },
    InquiryStatus.INTRO_MEETING: {
        "label": gettext_lazy("After intro meeting"),
        "subject": "Next steps after our introductory call",
        "body": (
            "Hello,\n\n"
            "It was good to talk with you. I think we have a good basis for working "
            "together, and I would be glad to welcome you as a client.\n\n"
            "As a next step, I will send you [the intake paperwork / a first "
            "appointment time]. Please let me know when you are ready.\n\n"
            "Best regards,\n"
            "[Your name]"
        ),
    },
    InquiryStatus.WAITLIST: {
        "label": gettext_lazy("Waitlist spot available"),
        "subject": "An opening is available — from the waitlist",
        "body": (
            "Hello,\n\n"
            "I wanted to let you know that I now have an opening in my schedule "
            "and thought of your inquiry.\n\n"
            "Are you still interested in starting sessions? "
            "I would appreciate hearing back from you by [date].\n\n"
            "Best regards,\n"
            "[Your name]"
        ),
    },
    InquiryStatus.IN_INTAKE: {
        "label": gettext_lazy("Intake documents"),
        "subject": "Your intake paperwork",
        "body": (
            "Hello,\n\n"
            "I'm glad you'd like to get started. Please complete the intake "
            "paperwork and upload it using your private link below:\n\n"
            "[Portal link]\n\n"
            "If you have any questions, feel free to reach out at any time.\n\n"
            "Best regards,\n"
            "[Your name]"
        ),
    },
    InquiryStatus.DECLINED: {
        "label": gettext_lazy("Friendly decline"),
        "subject": "Regarding your inquiry",
        "body": (
            "Hello,\n\n"
            "Thank you for your trust and for reaching out. After careful "
            "consideration, I'm sorry to say that I'm not able to take you on as a "
            "client at this time.\n\n"
            "I'd encourage you to reach out to other colleagues (for example via "
            "the Psychology Today therapist directory or your state counseling "
            "association). If you are in crisis, you can call or text 988 "
            "(Suicide & Crisis Lifeline, free and available 24/7).\n\n"
            "I wish you all the best.\n\n"
            "Best regards,\n"
            "[Your name]"
        ),
    },
    InquiryStatus.NOT_SUITABLE: {
        "label": gettext_lazy("Friendly decline (not a match)"),
        "subject": "Regarding your inquiry",
        "body": (
            "Hello,\n\n"
            "Thank you for your trust and for reaching out. After our conversation, "
            "I've come to the conclusion that I'm not the best fit for you — not "
            "because your concerns aren't important, but because my focus lies "
            "elsewhere.\n\n"
            "I'd recommend reaching out to colleagues who specialize in "
            "[area]. The Psychology Today therapist directory can help you find "
            "someone, and you can call or text 988 at any time if you are in crisis.\n\n"
            "I wish you all the best.\n\n"
            "Best regards,\n"
            "[Your name]"
        ),
    },
    InquiryStatus.UNREACHABLE: {
        "label": gettext_lazy("Closing — unreachable"),
        "subject": "Closing your inquiry",
        "body": (
            "Hello,\n\n"
            "I've tried to reach you a few times without success, so I'll close "
            "your inquiry for now.\n\n"
            "If you're still interested, you're always welcome to get in touch "
            "with me again.\n\n"
            "Best regards,\n"
            "[Your name]"
        ),
    },
}
