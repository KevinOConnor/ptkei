CP := cp

SRCS = $(shell ls *.wml)
OBJS = $(subst .wml,.html,$(SRCS))

%.html: %.wml
	wml -n -o $@ $<

all: $(OBJS)
	$(CP) ../../doc/*.html .
	if [ ! -d pics ]; then mkdir pics;fi
	$(CP) ../../doc/pics/*.png pics

clean:
	$(RM) $(OBJS) *~
	$(RM) *.html
	$(RM) -r pics

dist-clean:
	$(RM) *~

index.html: index.wml ../tmpl/template.wml
