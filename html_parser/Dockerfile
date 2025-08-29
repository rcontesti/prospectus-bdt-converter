# Use an official Python runtime as a parent image
FROM python:3.9-slim-buster

# Set the working directory in the container
WORKDIR /app/html_parser

# Install any needed packages specified in requirements.txt
# In this case, only pytest is needed for testing
RUN pip install pytest

# Copy the current directory contents into the container at /app/html_parser
COPY . /app/html_parser

# Command to run the application (default, can be overridden)
# This example assumes you might want to run the splitter directly
# CMD ["python", "src/html_regex_page_splitter.py"]
