import yaml
from pathlib import Path
from .rules.base import Rule, Category, Action, RuleMatch
from .rules.word_filter import WordFilterRule
from .rules.sensitive_info import AadhaarFilterRule
from .rules.denied_topics import DeniedTopicRule
from .rules.content_filter import PromptInjectionRule
from .rules.contextual_grounding import ContextualGroundingRule
from .rules.automated_reasoning import ArithmeticCheckRule


def load_rules(config_path: Path) -> list[Rule]:
    with open(config_path) as f:
        config = yaml.safe_load(f)

    rules = []
    for rule_def in config['rules']:
        rule_type = rule_def['type']
        action = Action(rule_def.get('action', 'block'))

        if rule_type == 'word_filter':
            rules.append(WordFilterRule(
                rule_id=rule_def['rule_id'],
                banned_words=rule_def['banned_words'],
                action=action,
            ))
        elif rule_type == 'aadhaar':
            rules.append(AadhaarFilterRule(
                rule_id=rule_def['rule_id'],
                action=action,
            ))
        elif rule_type == 'denied_topic':
            rules.append(DeniedTopicRule(
                rule_id=rule_def['rule_id'],
                topic_name=rule_def['topic_name'],
                trigger_phrases=rule_def['trigger_phrases'],
                action=action,
            ))
        elif rule_type == 'prompt_injection':
            rules.append(PromptInjectionRule(
                rule_id=rule_def['rule_id'],
                action=action,
            ))
        elif rule_type == 'contextual_grounding':
            rules.append(ContextualGroundingRule(
                rule_id=rule_def['rule_id'],
                action=action,
            ))
        elif rule_type == 'arithmetic_check':
            rules.append(ArithmeticCheckRule(
                rule_id=rule_def['rule_id'],
                action=action,
            ))
        else:
            raise ValueError(f"Unknown rule type: {rule_type}")

    return rules


def evaluate(
    rules: list[Rule], text: str, direction: str, context: dict | None = None
) -> list[RuleMatch]:
    """Run all rules against the text. Return matches in order."""
    matches = []
    for rule in rules:
        result = rule.check(text, direction, context=context)
        if result:
            matches.append(result)
    return matches
