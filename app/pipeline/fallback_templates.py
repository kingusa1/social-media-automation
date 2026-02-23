"""Template-based fallback posts when AI generation fails or validation rejects the output.

Provides multiple templates per project for variety.
No links in any posts - pure content only.
"""
import random
import logging

logger = logging.getLogger(__name__)

INFINITEO_LINKEDIN_TEMPLATES = [
    """{emoji} {title} - This Changes EVERYTHING!



Most people aren't paying attention to this. But if you're in business, you NEED to know what just happened.



{description}



Here's why this is a GAME-CHANGER:

{bullet} It fundamentally shifts how businesses operate
{bullet} Companies that adapt NOW will dominate their market
{bullet} Manual workflows just became obsolete overnight



What this solves:

- Businesses wasting hours on repetitive tasks
- Teams drowning in manual processes
- Organizations falling behind competitors who automate



At Infiniteo, we help businesses turn exactly these breakthroughs into real automation. We architect end-to-end systems that eliminate manual work and let your team focus on what actually moves the needle.



This isn't just news. It's the future arriving ahead of schedule.



Who else sees how BIG this is? Drop a comment below! {down}



#Infiniteo #Automation #AI #BusinessAutomation #DigitalTransformation #WorkflowAutomation""",

    """{emoji} BREAKING: {title}



I just came across something that every business leader needs to see.



{description}



The implications are MASSIVE:

{bullet} Efficiency gains that were impossible just months ago
{bullet} A completely new approach to business operations
{bullet} The automation gap between leaders and laggards just widened



What does this solve for YOUR business?

- Eliminates bottlenecks in your workflow
- Frees your team to focus on strategy, not busywork
- Gives you a competitive edge that compounds over time



This is exactly why we built Infiniteo - to help organizations harness these breakthroughs BEFORE their competitors do. We don't just follow trends. We turn them into operational advantage.



The question isn't IF you should automate. It's how fast you can move.



What's the #1 manual process holding YOUR business back? Let's discuss! {down}



#Infiniteo #Automation #BusinessTransformation #AI #ProcessOptimization""",
]

INFINITEO_TWITTER_TEMPLATES = [
    "{emoji} {short_title}\n\nThis changes EVERYTHING for business automation. The companies that move NOW will dominate.\n\n#Infiniteo #Automation #AI",
    "{emoji} BREAKING: {short_title}\n\nManual workflows just became obsolete. The future is HERE.\n\n#Infiniteo #BusinessAutomation",
    "{emoji} {short_title}\n\nThe automation revolution just accelerated. Are you ready?\n\n#Infiniteo #AI #Automation",
]

YOUROPS_LINKEDIN_TEMPLATES = [
    """{emoji} {title} - Ops Teams, Pay Attention!



This is a BIG deal for anyone running production infrastructure.



{description}



Why this matters NOW:

{bullet} Reliability standards just got raised
{bullet} Teams that adopt this will see fewer incidents
{bullet} The gap between good ops and great ops just widened



What this solves:

- Alert fatigue and incident overload
- Inconsistent deployment pipelines
- Infrastructure that doesn't scale with your business



At YourOps, we help teams build operational foundations that actually hold up under pressure. We've seen firsthand how the right systems turn chaotic ops into calm, predictable operations.



The best ops teams don't just react. They build systems that prevent problems before they happen.



What's the biggest ops challenge your team is facing right now? {down}



#YourOps #DevOps #ITOps #SRE #CloudOps #Infrastructure #OperationalExcellence""",

    """{emoji} BREAKING: {title}



Every SRE and ops engineer needs to see this.



{description}



The implications are huge:

{bullet} A new standard for operational excellence
{bullet} Better reliability with less manual toil
{bullet} Smarter incident response and prevention



At YourOps, we believe great operations is the backbone of every successful tech organization. This is exactly the kind of shift that separates world-class ops from the rest.



How is your team adapting to changes like this? {down}



#YourOps #DevOps #SRE #CloudOps #PlatformEngineering #Kubernetes""",
]

YOUROPS_TWITTER_TEMPLATES = [
    "{emoji} {short_title}\n\nReliability isn't luck. It's engineering. This changes the game for ops teams.\n\n#YourOps #DevOps #SRE",
    "{emoji} BREAKING: {short_title}\n\nOps teams, take note. This is BIG.\n\n#YourOps #ITOps #CloudOps",
    "{emoji} {short_title}\n\nThe future of infrastructure just shifted. Are your ops ready?\n\n#YourOps #DevOps #Infrastructure",
]

EMOJIS = {
    "infiniteo": ["🚀", "⚡", "🎯", "💡", "🔗", "🏗️", "🔥", "🤯", "💥"],
    "yourops": ["🔧", "⚙️", "📊", "🛡️", "🔍", "💻", "🔥", "⚡"],
}

BULLET_EMOJIS = ["•", "🔹", "⚡", "✅", "🎯"]
DOWN_EMOJIS = ["👇", "⬇️"]


def generate_fallback_posts(
    article_title: str,
    article_url: str = "",
    article_description: str = "",
    project_id: str = "infiniteo",
) -> tuple[str, str]:
    """Generate fallback LinkedIn and Twitter posts from templates.

    Returns: (linkedin_post, twitter_post)
    """
    emoji = random.choice(EMOJIS.get(project_id, ["📢"]))
    bullet = random.choice(BULLET_EMOJIS)
    down = random.choice(DOWN_EMOJIS)
    short_title = article_title[:120] if article_title else "Latest Industry Update"
    description = article_description[:300] + "..." if article_description and len(article_description) > 300 else (article_description or "")

    template_vars = {
        "emoji": emoji,
        "title": article_title or "Industry Update",
        "short_title": short_title,
        "description": description,
        "bullet": bullet,
        "down": down,
    }

    if project_id == "infiniteo":
        li_templates = INFINITEO_LINKEDIN_TEMPLATES
        tw_templates = INFINITEO_TWITTER_TEMPLATES
    elif project_id == "yourops":
        li_templates = YOUROPS_LINKEDIN_TEMPLATES
        tw_templates = YOUROPS_TWITTER_TEMPLATES
    else:
        li_templates = INFINITEO_LINKEDIN_TEMPLATES
        tw_templates = INFINITEO_TWITTER_TEMPLATES

    linkedin_post = random.choice(li_templates).format(**template_vars)
    twitter_post = random.choice(tw_templates).format(**template_vars)

    # Ensure Twitter is under 280 chars
    if len(twitter_post) > 280:
        twitter_post = twitter_post[:277] + "..."

    logger.info(f"Generated fallback posts for project {project_id}")
    return linkedin_post, twitter_post
