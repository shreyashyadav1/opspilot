from opspilot_agent.prompts import alert_message


def test_alert_message_names_the_service_and_firing_time():
    text = alert_message(
        "Checkout error rate above SLO", "storefront", "5xx above 2%", started_minutes_ago=3.4
    )
    assert text.splitlines() == [
        "ALERT: Checkout error rate above SLO",
        "Service: storefront",
        "Details: 5xx above 2%",
        "Firing for about 3 minutes.",
        "Investigate the root cause and submit a diagnosis.",
    ]


def test_alert_message_without_a_service_or_details():
    text = alert_message("Checkout latency above SLO", None)
    assert "Service:" not in text
    assert "Details: Checkout latency above SLO" in text
