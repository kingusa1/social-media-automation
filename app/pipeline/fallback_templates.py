"""Template-based fallback posts when AI generation fails or validation rejects the output.

Provides multiple templates per project for variety.
Faithfully replicates the n8n Create Fallback Posts node logic.
"""
import random
import logging

logger = logging.getLogger(__name__)

INFINITEO_LINKEDIN_TEMPLATES = [
    """{emoji} {title}

The landscape of business automation continues to evolve at an unprecedented pace. This latest development highlights key trends that forward-thinking leaders need to understand.

{description}

At Infiniteo, we're committed to staying at the forefront of automation innovation. Our mission is to liberate businesses from manual workflows and empower them to focus on what truly matters - strategy and growth.

Key takeaways:
- Automation is transforming how organizations operate
- Strategic execution beats manual processes every time
- The future belongs to those who automate now

This is exactly why we exist - to empower businesses with the automation they need to thrive.

Read the full article: {link}

What's your take on this development? How is your organization embracing automation?

#Infiniteo #Automation #AI #BusinessAutomation #DigitalTransformation #WorkflowAutomation""",

    """{emoji} {title}

Another signal that the automation revolution is accelerating. For business leaders still relying on manual processes, the gap is widening.

{description}

At Infiniteo, we see this every day - organizations that automate early gain compounding advantages. Those that wait fall further behind.

The question isn't whether to automate. It's how fast you can move.

Read more: {link}

Are you leading or lagging in automation adoption?

#Infiniteo #Automation #BusinessTransformation #AI #ProcessOptimization""",
]

INFINITEO_TWITTER_TEMPLATES = [
    "{emoji} {short_title}\n\nAutomation isn't optional anymore. It's the new baseline.\n\n{link}\n\n#Infiniteo #Automation #AI",
    "{emoji} {short_title}\n\nManual workflows are the bottleneck. Automation is the breakthrough.\n\n{link}\n\n#Infiniteo #BusinessAutomation",
    "{emoji} Big moves in automation. {short_title}\n\n{link}\n\n#Infiniteo #AI #Automation",
]

YOUROPS_LINKEDIN_TEMPLATES = [
    """{emoji} {title}

The ops landscape continues to evolve rapidly. This development is particularly relevant for teams focused on reliability and operational excellence.

{description}

At YourOps, we understand that operational excellence isn't just about tools - it's about building reliable systems that scale with your business.

Key operational insights:
- Reliability at scale requires intentional practices
- Automation reduces toil and improves consistency
- Observability is the foundation of operational intelligence

Read the full article: {link}

How is your ops team adapting to these changes?

#YourOps #DevOps #ITOps #SRE #CloudOps #Infrastructure #OperationalExcellence""",

    """{emoji} {title}

Worth reading for every ops team. The patterns discussed here are reshaping how we think about system reliability and operational efficiency.

{description}

At YourOps, we believe that great operations is the backbone of every successful technology organization. This is exactly the kind of insight that drives better operational outcomes.

Read more: {link}

What operational challenges are you solving right now?

#YourOps #DevOps #SRE #CloudOps #PlatformEngineering #Kubernetes""",
]

YOUROPS_TWITTER_TEMPLATES = [
    "{emoji} {short_title}\n\nReliability isn't luck. It's engineering.\n\n{link}\n\n#YourOps #DevOps #SRE",
    "{emoji} {short_title}\n\nOps teams, take note.\n\n{link}\n\n#YourOps #ITOps #CloudOps",
    "{emoji} Ops insight: {short_title}\n\n{link}\n\n#YourOps #DevOps #Infrastructure",
]

EMOJIS = {
    "infiniteo": ["🚀", "⚡", "🎯", "💡", "🔗", "🏗️"],
    "yourops": ["🔧", "⚙️", "📊", "🛡️", "🔍", "💻"],
}


def generate_fallback_posts(
    article_title: str,
    article_url: str,
    article_description: str,
    project_id: str,
) -> tuple[str, str]:
    """Generate fallback LinkedIn and Twitter posts from templates.

    Returns: (linkedin_post, twitter_post)
    """
    emoji = random.choice(EMOJIS.get(project_id, ["📢"]))
    short_title = article_title[:120] if article_title else "Latest Industry Update"
    description = article_description[:200] + "..." if article_description and len(article_description) > 200 else (article_description or "")

    template_vars = {
        "emoji": emoji,
        "title": article_title or "Industry Update",
        "short_title": short_title,
        "link": article_url or "",
        "description": description,
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
