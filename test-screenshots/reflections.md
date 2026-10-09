# Reflections

## **One design decision you made and why:**

In the method save_support_interaction I decided to truncate the text so that only the customer message would be added to the memory. Since the method retrieve_customer_context added the memories from the long-term strategies to the user query, not truncating the last user message in the interaction means that we are sending the memories again to be stored. This would make memory larger in size than it needs to be by recording facts twice, which is unnecessary.

## **One challenge you encountered and how you solved it:**

In the first iteration of the agent, it was creating multiple browsing sessions without being able to fetch the required data from the udacity website. I solved this by testing progressively larger timeouts and adding a brief additional time for the browser warm up.

## **How you would extend this agent for a production environment:**

I would modify the prompt to tell it to encourage users to join the loyalty program. This could increase ROI for the company and gather additional data points on users. I would also provide the ability to escalate the conversation to a human if the interaction gets too complex, as well as providing safeguards to avoid unintended use. Additionally, clear steering about what websites the agent is allowed to visit is missing and should be added before allowing real customer interaction.