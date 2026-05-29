# Roadmap for Pulpit: Activities for Next Versions
## [0.24]
Structural and behavioural similarity
generalize UI for measures depending on other measures or values

## [1.0]
Have a review of all measurements available in Pulpit. Read documentation for having a good grasp of what is the Pulpit goal. Then:
1. find measures that Pulpit offers and that aren't useful in this specific case;
2. find measures that Pulpit doesn't offers yet and that can be useful in this specific case.
Let me choose which to remove and which to accept, if any.

- Zenodo registration
- Have a deep inspection of Python code for calculating channels measures, network measures, community strategies, consensus matrix, structural similarity, robustness, and vacancies. Do search for bugs, implementations that doesn't have a strong academic validation, and incoherence between different calculations. Produce a detailed todo list and let me approve each action before writing anything.
- Have a deep inspection of Python code for calculating channels measures, network measures, community strategies, consensus matrix, structural similarity, robustness, and vacancies. Take care documentation is coherent with the code. Academic validation always has priority in choosing if adapting documentation to the code or the code to the documentation.
- Have a deep inspection of Python code, search for bugs, bad practices and dead code
- Have a deep inspection of JS code, search for bugs, bad practices and dead code
- Have a deep inspection of HTML and CSS code, search for bugs, bad practices and dead code
- Have a deep inspection of HTML code, make sure the app and the HTML output of analysis are respecting accessibility rules and can provide a decent experience for people using screen readers
- Have a deep inspection of all options accepted by commands, verify their coherence, look for inconsistencies and bad practices
- I need strong layout coherence through all the software, inspect webapp templates and HTML outputs
- Explore the Python code looking for factorizations, propose them to me and wait for approval.
- Explore the JS code looking for factorizations, propose them to me and wait for approval.
- Explore the CSS code looking for factorizations, propose them to me and wait for approval.
- Explore the Django template code looking for factorizations, propose them to me and wait for approval.


## [2.0]
Coordination index, as a new measure. It needs a new graph
https://github.com/textgain/grasp



Analyze how Infomap community detection is used in Pulpit. Verify it's used in a way that's academically validated and that code and documentation are coherent.
Take care documentation is structured with a title, a one liner as short description, a longer description, at least one reference (more than one if this is important), what does it means in practice (considering Pulpit goals) and a clear example.


Review explanaitions for measures in /docs/network-measures.md
They should be structured with a title, a one liner as short description, a longer description, at least one reference (more than one if this is important), what does it means in practice (considering Pulpit goals) and a clear example.
"In practice" and "example" should be worded in non technical ways, in particular "example" should be a clear text aimed a journalists, activists and other people interested in the outcome but not in the technical details.
References should be essentials, we do not expect to have here a complete list of references.
Even the introduction should be short and not going deep in implementation details.
The first one òiner should be readable and meaningful for non technical people.

Try to keep coherence between different measures, not only for the content but even for the length of the text.



.has the right citations, a readable description,
Have a deep inspection of Python code for calculating Structural and behavioural similarity. Do search for bugs, implementations that doesn't have a strong academic validation, and incoherence between different calculations. Produce a detailed todo list and let me approve each action before writing anything.
