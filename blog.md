# Create an article

## Title

Weekend Showcase Challenge: FirstCommit

## Description

FirstCommit helps developers understand unfamiliar GitHub repositories, find issues that match their experience, and take a practical first step toward open-source contribution.

## Tags

#application, AWS, Amazon Bedrock, Open Source, Developer Tools

## Body

# Weekend Showcase Challenge: FirstCommit

Open source has something for everyone, but finding a place to begin can be difficult. A new contributor may discover an exciting GitHub project and still feel stuck because the repository has hundreds of files, unfamiliar tools, and issues that are hard to understand. Even an issue marked “good first issue” does not always explain what to read, what to change, or what skills are needed.

That is the problem I wanted to solve with FirstCommit.

[Try the live FirstCommit app](https://wvnzqjk5n2r2bl3s6xtw7bbwbm0zmlup.lambda-url.us-east-1.on.aws/)

## The vision

FirstCommit turns an unfamiliar public GitHub repository into a simple contributor roadmap. A user enters a repository URL, chooses their experience level and goal, and receives guidance designed for that specific project.

The app explains what the project does in plain language, highlights the most important files, describes the main areas of the codebase, and recommends a reading order. It also looks at open issues and points the user toward work that may fit their current experience.

The experience is designed around four questions:

- What does this project do?
- Where should I start reading?
- Which issue could I understand?
- What should I do before opening a pull request?

FirstCommit is meant to help people understand before they change. It does not try to complete an entire contribution for them. Instead, it gives them enough context to take the next step with confidence.

## How I built it

I started by mapping the contributor journey rather than starting with technology. The first screen needed to be simple: paste a GitHub URL, choose an experience level, and choose a goal. From there, I designed the result as a dashboard instead of a single AI-generated paragraph.

The application first collects repository facts such as the project description, programming languages, README, contribution guide, file structure, and open issues. It then identifies useful starting points, such as project documentation, package files, entry points, configuration, and tests.

A key decision was to keep facts separate from interpretation. Information that can be read directly from GitHub is shown as repository evidence. Amazon Bedrock is used to explain that evidence in a more helpful way. When the information is uncertain, the app can present it as a likely location instead of pretending it is guaranteed.

One of the biggest challenges was that every repository is organized differently. A solution that works for a small JavaScript project may not work for a Python service or a containerized application. I addressed this by looking for patterns instead of assuming one fixed structure. I also limited the context sent for analysis so that large repositories do not overwhelm the experience.

Another important decision was adding a fallback. If an AI request is unavailable or temporarily fails, FirstCommit can still return a useful report from the repository metadata and file tree. The product should remain helpful even when one part of the system is unavailable.

## AWS architecture

FirstCommit is deployed as a serverless application with [AWS SAM](https://aws.amazon.com/serverless/sam/).

The browser sends a request to a public [AWS Lambda](https://aws.amazon.com/lambda/) Function URL. The Lambda function validates the GitHub URL, reads public repository information through the GitHub API, and builds a smaller set of useful evidence.

That evidence can be sent to [Amazon Bedrock](https://aws.amazon.com/bedrock/) with Amazon Nova Lite to generate the project explanation, recommended reading order, issue guidance, and repository Q&A. The scan result is saved in [Amazon DynamoDB](https://aws.amazon.com/dynamodb/) so the application can reuse it when the contributor asks a follow-up question.

The flow is:

User → Lambda Function URL → GitHub API and Amazon Bedrock → DynamoDB → Contributor dashboard

This design keeps the first version easy to deploy and avoids managing servers. It also gives the application room to grow with features such as saved profiles, progress tracking, and daily project recommendations.

## What I learned across the summer

This project taught me that a good AI application is not only about calling a model. The surrounding product decisions matter just as much.

I learned how important it is to reduce and organize context before asking a model for help. I learned to separate reliable data from suggestions and to make uncertainty visible. I also learned that a fallback path is essential when building a user experience around an external service.

Across the summer, I became more comfortable designing with AWS Lambda, Amazon Bedrock, DynamoDB, IAM permissions, and SAM deployment. More importantly, I learned to start with the user’s confusion and work backward toward the architecture.

## Closing

FirstCommit is built around a simple belief: open source should not feel overwhelming. If a developer can understand the project, find where their skills fit, and see one clear next step, making a first contribution becomes much more achievable.

[Explore FirstCommit](https://wvnzqjk5n2r2bl3s6xtw7bbwbm0zmlup.lambda-url.us-east-1.on.aws/) and find your way into open source.

Builder who inspired me: @gocools (Gokul Upadhyay Guragain)

