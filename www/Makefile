
SRCS = $(shell ls *.wml)
OBJS = $(subst .wml,.html,$(SRCS))

%.html: %.wml
	wml -n -o $@ $<

all: $(OBJS)
	(cd doc;$(MAKE) all)

clean:
	$(RM) $(OBJS) *~
	(cd doc;$(MAKE) clean)

dist-clean:
	$(RM) *~
	(cd doc;$(MAKE) dist-clean)

upload: dist-clean
	lftp -f cmd.lftp

contact.html: contact.wml tmpl/template.wml
download.html: download.wml tmpl/template.wml
development.html: development.wml tmpl/template.wml
features.html: features.wml tmpl/template.wml
index.html: index.wml tmpl/template.wml
macpics.html: macpics.wml tmpl/template.wml
news.html: news.wml tmpl/template.wml
projects.html: projects.wml tmpl/template.wml
screenshots.html: screenshots.wml tmpl/template.wml
