/* This entire file is licensed under GNU General Public License v3.0
 *
 * Copyright 2021- sfwbar maintainers
 */

#include "window.h"
#include "gui/bar.h"
#include "gui/capture.h"
#include "gui/css.h"
#include "gui/flowgrid.h"
#include "gui/flowitem.h"
#include "gui/monitor.h"
#include "gui/popup.h"
#include "gui/scaleimage.h"

G_DEFINE_TYPE_WITH_CODE (FlowGrid, flow_grid, BASE_WIDGET_TYPE,
    G_ADD_PRIVATE(FlowGrid))

enum {
  FLOW_GRID_LABELS = 1,
  FLOW_GRID_ICONS,
  FLOW_GRID_PREVIEW,
  FLOW_GRID_TOOLTIPS,
  FLOW_GRID_TITLE_WIDTH,
  FLOW_GRID_SORT,
  FLOW_GRID_COLS,
  FLOW_GRID_ROWS,
  FLOW_GRID_PRIMARY_AXIS,
  FLOW_GRID_VALUE_OVERRIDE,
  FLOW_GRID_TOOLTIP_OVERRIDE,
  FLOW_GRID_SORT_REVERSE,
  FLOW_GRID_OVERFLOW,
};


GEnumValue flow_grid_axis[] = {
  { FLOW_GRID_AXIS_DEFAULT, "default", "default" },
  { FLOW_GRID_AXIS_ROWS, "rows", "rows" },
  { FLOW_GRID_AXIS_COLS, "cols", "cols" },
};

/* FlickOS: overflow = true on a one-row grid (Redmond's taskbar). The
 * items that fit stay in the bar; the others go to a list in a pop-up
 * (window#taskbar_more, grid#taskbar_more_grid) that the more button at
 * the bar's end (button#taskbar_more) opens on a click. Upstream's grid
 * grew with every item and pushed the rest of the bar off the screen. */
static gboolean flow_grid_overflow_on ( FlowGridPrivate *priv )
{
  return priv->overflow && priv->rows == 1;
}

static gint flow_grid_child_width ( GtkWidget *child )
{
  gint w;

  gtk_widget_get_preferred_width(child, NULL, &w);
  return w;
}

static gboolean flow_grid_more_shown ( FlowGridPrivate *priv )
{
  return priv->more_button && gtk_widget_get_parent(priv->more_button);
}

/* The more button's width; while it's out of the bar, an item's (both are
 * one icon in the same button shape). */
static gint flow_grid_more_width ( GtkWidget *self )
{
  FlowGridPrivate *priv;
  GList *iter;

  priv = flow_grid_get_instance_private(FLOW_GRID(self));
  if(flow_grid_more_shown(priv))
    return flow_grid_child_width(priv->more_button);
  for(iter=priv->children; iter; iter=g_list_next(iter))
    if(flow_item_get_active(iter->data))
      return flow_grid_child_width(iter->data);
  return 0;
}

/* How much wider the bar's part would be with the listed items in it and
 * no more button. */
static gint flow_grid_overflow_extra ( GtkWidget *self )
{
  FlowGridPrivate *priv;
  GList *iter;
  gint spacing, extra = 0;

  priv = flow_grid_get_instance_private(FLOW_GRID(self));
  if(!priv->more_grid)
    return 0;

  spacing = gtk_grid_get_column_spacing(GTK_GRID(priv->grid));
  for(iter=priv->children; iter; iter=g_list_next(iter))
    if(flow_item_get_active(iter->data) &&
        gtk_widget_get_parent(iter->data) == priv->more_grid)
      extra += flow_grid_child_width(iter->data) + spacing;
  if(flow_grid_more_shown(priv))
    extra -= flow_grid_child_width(priv->more_button) + spacing;

  return MAX(extra, 0);
}

/* How many items fit in width: -1 for all, else as many as fit next to
 * the more button. */
static gint flow_grid_overflow_capacity ( GtkWidget *self, gint width )
{
  FlowGridPrivate *priv;
  GList *iter;
  gint spacing, total, n, used, cap, w;

  priv = flow_grid_get_instance_private(FLOW_GRID(self));
  spacing = gtk_grid_get_column_spacing(GTK_GRID(priv->grid));

  total = 0;
  n = 0;
  for(iter=priv->children; iter; iter=g_list_next(iter))
    if(flow_item_get_active(iter->data))
      total += flow_grid_child_width(iter->data) + (n++? spacing : 0);
  if(total <= width)
    return -1;

  used = flow_grid_more_width(self);
  cap = 0;
  for(iter=priv->children; iter; iter=g_list_next(iter))
    if(flow_item_get_active(iter->data))
    {
      w = flow_grid_child_width(iter->data);
      if(used + spacing + w > width)
        break;
      used += spacing + w;
      cap++;
    }

  return cap;
}

static void flow_grid_get_preferred_width (GtkWidget *self, gint *minimal,
    gint *natural)
{
  FlowGridPrivate *priv;

  g_return_if_fail(IS_FLOW_GRID(self));
  priv = flow_grid_get_instance_private(FLOW_GRID(self));

  GTK_WIDGET_CLASS(flow_grid_parent_class)->get_preferred_width(
      self, minimal, natural);

  if(priv->rows>0 && FLOW_GRID_GET_CLASS(self)->limit)
    *minimal = MIN(*natural, 0);

  /* FlickOS: an overflowing grid can be given any width; it asks for what
   * all its items would take in the bar. */
  if(flow_grid_overflow_on(priv))
  {
    *natural += flow_grid_overflow_extra(self);
    *minimal = 0;
  }
}

static void flow_grid_get_preferred_height (GtkWidget *self, gint *minimal,
    gint *natural)
{
  FlowGridPrivate *priv;

  g_return_if_fail(IS_FLOW_GRID(self));
  priv = flow_grid_get_instance_private(FLOW_GRID(self));

  GTK_WIDGET_CLASS(flow_grid_parent_class)->get_preferred_height(
      self, minimal, natural);

  if(priv->cols>0 && FLOW_GRID_GET_CLASS(self)->limit)
    *minimal = MIN(*natural, 0);
}

static void flow_grid_schedule_update ( GtkWidget *self );

/* FlickOS: the number of items that fit follows the width the bar gives. */
static void flow_grid_size_allocate ( GtkWidget *self, GtkAllocation *alloc )
{
  FlowGridPrivate *priv;
  GtkStyleContext *style;
  GtkStateFlags flags;
  GtkBorder margin, border, padding;
  gint cap;

  g_return_if_fail(IS_FLOW_GRID(self));
  priv = flow_grid_get_instance_private(FLOW_GRID(self));

  GTK_WIDGET_CLASS(flow_grid_parent_class)->size_allocate(self, alloc);

  if(!flow_grid_overflow_on(priv))
    return;
  /* The width the bar gives the grid, not the inner grid's own: with
   * halign start that is only as wide as the items in it, so items never
   * came back when the bar got room (media buttons gone, a wider screen). */
  style = gtk_widget_get_style_context(priv->grid);
  flags = gtk_style_context_get_state(style);
  gtk_style_context_get_margin(style, flags, &margin);
  gtk_style_context_get_border(style, flags, &border);
  gtk_style_context_get_padding(style, flags, &padding);
  cap = flow_grid_overflow_capacity(self, gtk_widget_get_allocated_width(self)
      - margin.left - margin.right - border.left - border.right
      - padding.left - padding.right);
  if(cap != priv->capacity)
  {
    priv->capacity = cap;
    priv->invalid = TRUE;
    flow_grid_schedule_update(self);
  }
}

static void flow_grid_more_close ( GtkWidget *self )
{
  FlowGridPrivate *priv;

  priv = flow_grid_get_instance_private(FLOW_GRID(self));
  if(priv->more_window && gtk_widget_get_visible(priv->more_window))
    popup_popdown(priv->more_window);
}

static gboolean flow_grid_more_close_idle ( GtkWidget *self )
{
  if(!gtk_widget_in_destruction(self))
    flow_grid_more_close(self);
  g_object_unref(self);
  return G_SOURCE_REMOVE;
}

static void flow_grid_more_clicked ( GtkWidget *button, GtkWidget *self )
{
  FlowGridPrivate *priv;
  GdkEvent *ev;
  GdkSeat *seat = NULL;

  priv = flow_grid_get_instance_private(FLOW_GRID(self));

  if(gtk_widget_get_visible(priv->more_window))
  {
    flow_grid_more_close(self);
    return;
  }
  /* The click on this button that closed the list (outside it). */
  if(g_get_monotonic_time() - priv->more_closed < 300000)
    return;

  if( (ev = gtk_get_current_event()) )
  {
    if(gdk_event_get_device(ev))
      seat = gdk_device_get_seat(gdk_event_get_device(ev));
    gdk_event_free(ev);
  }
  popup_show(priv->more_button, priv->more_window, seat);
}

/* A click on a listed item (left or middle) closes the list once the item
 * has acted; connected to each item while it is in the list, so it runs
 * before the item's own handler, which stops the event. A right click
 * leaves the list open for the item's menu. */
static gboolean flow_grid_more_item_release ( GtkWidget *item,
    GdkEventButton *ev, GtkWidget *self )
{
  if(ev->button == 1 || ev->button == 2)
    g_idle_add((GSourceFunc)flow_grid_more_close_idle, g_object_ref(self));
  return FALSE;
}

static gboolean flow_grid_more_key ( GtkWidget *win, GdkEventKey *ev,
    GtkWidget *self )
{
  if(ev->keyval != GDK_KEY_Escape)
    return FALSE;
  flow_grid_more_close(self);
  return TRUE;
}

/* Closed by the compositor (a click outside it). */
static gboolean flow_grid_more_state ( GtkWidget *win,
    GdkEventWindowState *ev, GtkWidget *self )
{
  if(ev->changed_mask & GDK_WINDOW_STATE_WITHDRAWN &&
      ev->new_window_state & GDK_WINDOW_STATE_WITHDRAWN)
    flow_grid_more_close(self);
  return FALSE;
}

static void flow_grid_more_hide ( GtkWidget *win, GtkWidget *self )
{
  FlowGridPrivate *priv;

  priv = flow_grid_get_instance_private(FLOW_GRID(self));
  priv->more_closed = g_get_monotonic_time();
}

static void flow_grid_more_init ( GtkWidget *self )
{
  FlowGridPrivate *priv;
  GtkWidget *image, *button;

  priv = flow_grid_get_instance_private(FLOW_GRID(self));
  if(priv->more_button)
    return;

  /* An event box with a window of its own, so the list opens at the
   * button (popup_show places it by the parent's window). It is in the
   * grid only while items overflow: sfwbar's CSS shows hidden widgets. */
  priv->more_button = gtk_event_box_new();
  g_object_ref_sink(priv->more_button);
  button = gtk_button_new();
  gtk_widget_set_name(button, "taskbar_more");
  image = scale_image_new();
  scale_image_set_image(image, "view-more-horizontal-symbolic", NULL);
  gtk_container_add(GTK_CONTAINER(button), image);
  gtk_container_add(GTK_CONTAINER(priv->more_button), button);
  gtk_widget_show_all(priv->more_button);
  g_signal_connect(button, "clicked",
      G_CALLBACK(flow_grid_more_clicked), self);

  priv->more_window = gtk_window_new(GTK_WINDOW_POPUP);
  gtk_widget_set_name(priv->more_window, "taskbar_more");
  gtk_window_set_type_hint(GTK_WINDOW(priv->more_window),
      GDK_WINDOW_TYPE_HINT_POPUP_MENU);
  priv->more_grid = gtk_grid_new();
  gtk_widget_set_name(priv->more_grid, "taskbar_more_grid");
  gtk_container_add(GTK_CONTAINER(priv->more_window), priv->more_grid);
  gtk_widget_show(priv->more_grid);

  g_signal_connect(priv->more_window, "key-press-event",
      G_CALLBACK(flow_grid_more_key), self);
  g_signal_connect(priv->more_window, "window-state-event",
      G_CALLBACK(flow_grid_more_state), self);
  g_signal_connect(priv->more_window, "hide",
      G_CALLBACK(flow_grid_more_hide), self);
}

static void flow_grid_destroy( GtkWidget *self )
{
  FlowGridPrivate *priv;

  g_return_if_fail(IS_FLOW_GRID(self));
  priv = flow_grid_get_instance_private(FLOW_GRID(self));

  if(priv->update_h)
  {
    g_source_remove(priv->update_h);
    priv->update_h = 0;
  }
  g_list_free_full(g_steal_pointer(&priv->children),
      (GDestroyNotify)gtk_widget_destroy);
  if(priv->more_window)
  {
    gtk_widget_destroy(priv->more_window);
    priv->more_window = NULL;
    priv->more_grid = NULL;
  }
  if(priv->more_button)
  {
    gtk_widget_destroy(priv->more_button);
    g_clear_object(&priv->more_button);
  }
  GTK_WIDGET_CLASS(flow_grid_parent_class)->destroy(self);
}

static void flow_grid_style_updated ( GtkWidget *self )
{
  FlowGridPrivate *priv;
  gboolean h;

  g_return_if_fail(IS_FLOW_GRID(self));
  priv = flow_grid_get_instance_private(FLOW_GRID(self));

  gtk_widget_style_get(priv->grid, "row-homogeneous", &h, NULL);
  gtk_grid_set_row_homogeneous(GTK_GRID(priv->grid), h);
  gtk_widget_style_get(priv->grid, "column-homogeneous", &h, NULL);
  gtk_grid_set_column_homogeneous(GTK_GRID(priv->grid), h);

  GTK_WIDGET_CLASS(flow_grid_parent_class)->style_updated(self);
}

static void flow_grid_get_property ( GObject *self, guint id, GValue *value,
    GParamSpec *spec )
{
  FlowGridPrivate *priv;

  priv = flow_grid_get_instance_private(FLOW_GRID(self));

  switch(id)
  {
    case FLOW_GRID_LABELS:
      g_value_set_boolean(value, priv->labels);
      break;
    case FLOW_GRID_ICONS:
      g_value_set_boolean(value, priv->icons);
      break;
    case FLOW_GRID_PREVIEW:
      g_value_set_boolean(value, priv->preview);
      break;
    case FLOW_GRID_TOOLTIPS:
      g_value_set_boolean(value, priv->tooltips);
      break;
    case FLOW_GRID_TITLE_WIDTH:
      g_value_set_int(value, priv->title_width);
      break;
    case FLOW_GRID_SORT:
      g_value_set_boolean(value, priv->sort);
      break;
    case FLOW_GRID_SORT_REVERSE:
      g_value_set_boolean(value, priv->sort_reverse);
      break;
    case FLOW_GRID_COLS:
      g_value_set_int(value, priv->cols);
      break;
    case FLOW_GRID_ROWS:
      g_value_set_int(value, priv->rows);
      break;
    case FLOW_GRID_PRIMARY_AXIS:
      g_value_set_enum(value, priv->primary_axis);
      break;
    case FLOW_GRID_OVERFLOW:
      g_value_set_boolean(value, priv->overflow);
      break;
    case FLOW_GRID_VALUE_OVERRIDE:
    case FLOW_GRID_TOOLTIP_OVERRIDE:
      g_value_set_boxed(value, NULL);
      break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID(self, id, spec);
  }
}

static void flow_grid_set_property ( GObject *self, guint id,
    const GValue *value, GParamSpec *spec )
{
  FlowGridPrivate *priv;

  priv = flow_grid_get_instance_private(FLOW_GRID(self));
  switch(id)
  {
    case FLOW_GRID_LABELS:
      priv->labels = g_value_get_boolean(value);
      break;
    case FLOW_GRID_ICONS:
      priv->icons = g_value_get_boolean(value);
      break;
    case FLOW_GRID_PREVIEW:
      priv->preview = g_value_get_boolean(value);
      css_set_class(base_widget_get_child(GTK_WIDGET(self)), "preview",
          priv->preview & capture_support_check(CAPTURE_TYPE_WINDOW));
      break;
    case FLOW_GRID_TOOLTIPS:
      priv->tooltips = g_value_get_boolean(value);
      break;
    case FLOW_GRID_TITLE_WIDTH:
      priv->title_width = g_value_get_int(value);
      break;
    case FLOW_GRID_SORT:
      priv->sort = g_value_get_boolean(value);
      flow_grid_invalidate(GTK_WIDGET(self));
      break;
    case FLOW_GRID_SORT_REVERSE:
      priv->sort_reverse = g_value_get_boolean(value);
      flow_grid_invalidate(GTK_WIDGET(self));
      break;
    case FLOW_GRID_COLS:
      if(g_value_get_int(value)>=0)
      {
        priv->cols = g_value_get_int(value);
        if(priv->cols>0)
          priv->rows = 0;
        flow_grid_invalidate(GTK_WIDGET(self));
      }
      break;
    case FLOW_GRID_ROWS:
      if(g_value_get_int(value)>=0)
      {
        priv->rows = g_value_get_int(value);
        if(priv->rows>0)
          priv->cols = 0;
        flow_grid_invalidate(GTK_WIDGET(self));
      }
      break;
    case FLOW_GRID_PRIMARY_AXIS:
      priv->primary_axis = g_value_get_enum(value);
      flow_grid_invalidate(GTK_WIDGET(self));
      break;
    case FLOW_GRID_OVERFLOW:
      priv->overflow = g_value_get_boolean(value);
      priv->capacity = -1;
      flow_grid_invalidate(GTK_WIDGET(self));
      gtk_widget_queue_resize(GTK_WIDGET(self));
      break;
    case FLOW_GRID_VALUE_OVERRIDE:
    case FLOW_GRID_TOOLTIP_OVERRIDE:
      break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID(self, id, spec);
  }
}

static void flow_grid_mirror ( GtkWidget *dest, GtkWidget *src )
{
  BASE_WIDGET_CLASS(flow_grid_parent_class)->mirror(dest, src);

  g_object_bind_property(G_OBJECT(src), "labels",
      G_OBJECT(dest), "labels", G_BINDING_SYNC_CREATE);
  g_object_bind_property(G_OBJECT(src), "icons",
      G_OBJECT(dest), "icons", G_BINDING_SYNC_CREATE);
  g_object_bind_property(G_OBJECT(src), "preview",
      G_OBJECT(dest), "preview", G_BINDING_SYNC_CREATE);
  g_object_bind_property(G_OBJECT(src), "tooltips",
      G_OBJECT(dest), "tooltips", G_BINDING_SYNC_CREATE);
  g_object_bind_property(G_OBJECT(src), "title_width",
      G_OBJECT(dest), "title_width", G_BINDING_SYNC_CREATE);
  g_object_bind_property(G_OBJECT(src), "sort",
      G_OBJECT(dest), "sort", G_BINDING_SYNC_CREATE);
  g_object_bind_property(G_OBJECT(src), "sort_reverse",
      G_OBJECT(dest), "sort_reverse", G_BINDING_SYNC_CREATE);
  g_object_bind_property(G_OBJECT(src), "cols",
      G_OBJECT(dest), "cols", G_BINDING_SYNC_CREATE);
  g_object_bind_property(G_OBJECT(src), "rows",
      G_OBJECT(dest), "rows", G_BINDING_SYNC_CREATE);
  g_object_bind_property(G_OBJECT(src), "primary_axis",
      G_OBJECT(dest), "primary_axis", G_BINDING_SYNC_CREATE);
  g_object_bind_property(G_OBJECT(src), "overflow",
      G_OBJECT(dest), "overflow", G_BINDING_SYNC_CREATE);
}

static void flow_grid_class_init ( FlowGridClass *kclass )
{
  GtkWidgetClass *widget_class = GTK_WIDGET_CLASS(kclass);
  widget_class->get_preferred_width = flow_grid_get_preferred_width;
  widget_class->get_preferred_height = flow_grid_get_preferred_height;
  widget_class->destroy = flow_grid_destroy;
  widget_class->size_allocate = flow_grid_size_allocate;
  widget_class->style_updated = flow_grid_style_updated;

  kclass->limit = FALSE;
  kclass->fill = TRUE;

  G_OBJECT_CLASS(kclass)->get_property = flow_grid_get_property;
  G_OBJECT_CLASS(kclass)->set_property = flow_grid_set_property;
  BASE_WIDGET_CLASS(kclass)->mirror = flow_grid_mirror;

  g_object_class_install_property(G_OBJECT_CLASS(kclass), FLOW_GRID_LABELS,
      g_param_spec_boolean("labels", "labels", "sfwbar_config", TRUE,
        G_PARAM_READWRITE | G_PARAM_CONSTRUCT));
  g_object_class_install_property(G_OBJECT_CLASS(kclass), FLOW_GRID_ICONS,
      g_param_spec_boolean("icons", "icons", "sfwbar_config", FALSE,
        G_PARAM_READWRITE | G_PARAM_CONSTRUCT));
  g_object_class_install_property(G_OBJECT_CLASS(kclass), FLOW_GRID_PREVIEW,
      g_param_spec_boolean("preview", "preview", "sfwbar_config", FALSE,
        G_PARAM_READWRITE | G_PARAM_CONSTRUCT));
  g_object_class_install_property(G_OBJECT_CLASS(kclass), FLOW_GRID_TOOLTIPS,
      g_param_spec_boolean("tooltips", "tooltips", "sfwbar_config", FALSE,
        G_PARAM_READWRITE | G_PARAM_CONSTRUCT));
  g_object_class_install_property(G_OBJECT_CLASS(kclass),
      FLOW_GRID_TITLE_WIDTH, g_param_spec_int("title_width", "title_width",
        "sfwbar_config", -1, INT_MAX, -1, G_PARAM_READWRITE |
        G_PARAM_CONSTRUCT));
  g_object_class_install_property(G_OBJECT_CLASS(kclass), FLOW_GRID_SORT,
      g_param_spec_boolean("sort", "sort", "sfwbar_config", TRUE,
        G_PARAM_READWRITE | G_PARAM_CONSTRUCT));
  g_object_class_install_property(G_OBJECT_CLASS(kclass), FLOW_GRID_SORT_REVERSE,
      g_param_spec_boolean("sort_reverse", "sort_reverse", "sfwbar_config", FALSE,
        G_PARAM_READWRITE | G_PARAM_CONSTRUCT));
  g_object_class_install_property(G_OBJECT_CLASS(kclass), FLOW_GRID_COLS,
    g_param_spec_int("cols", "cols", "sfwbar_config", -1, INT_MAX, 0,
      G_PARAM_READWRITE | G_PARAM_CONSTRUCT));
  g_object_class_install_property(G_OBJECT_CLASS(kclass), FLOW_GRID_ROWS,
    g_param_spec_int("rows", "rows", "sfwbar_config", -1, INT_MAX, 1,
      G_PARAM_READWRITE | G_PARAM_CONSTRUCT));
  g_object_class_install_property(G_OBJECT_CLASS(kclass),
      FLOW_GRID_PRIMARY_AXIS,
      g_param_spec_enum("primary_axis", "primary_axis", "sfwbar_config",
        g_enum_register_static("flow_grid_axis", flow_grid_axis),
        FLOW_GRID_AXIS_DEFAULT, G_PARAM_READWRITE));
  g_object_class_install_property(G_OBJECT_CLASS(kclass), FLOW_GRID_OVERFLOW,
      g_param_spec_boolean("overflow", "overflow", "sfwbar_config", FALSE,
        G_PARAM_READWRITE));
  g_object_class_override_property(G_OBJECT_CLASS(kclass),
      FLOW_GRID_VALUE_OVERRIDE, "value");
  g_object_class_override_property(G_OBJECT_CLASS(kclass),
      FLOW_GRID_TOOLTIP_OVERRIDE, "tooltip");
}

static void flow_grid_init ( FlowGrid *self )
{
  FlowGridPrivate *priv;
  gchar *sig;

  g_return_if_fail(IS_FLOW_GRID(self));
  priv = flow_grid_get_instance_private(FLOW_GRID(self));

  priv->grid = gtk_grid_new();
  gtk_container_add(GTK_CONTAINER(self), priv->grid);
  priv->capacity = -1;

  sig = g_strdup_printf("flow-item-%p", (void *)self);
  priv->dnd_target = gtk_target_entry_new(sig, 0, SFWB_DND_TARGET_FLOW_ITEM);
  g_free(sig);
}

void flow_grid_set_dnd_target ( GtkWidget *self, GtkTargetEntry *target )
{
  FlowGridPrivate *priv;

  g_return_if_fail(IS_FLOW_GRID(self));
  priv = flow_grid_get_instance_private(FLOW_GRID(self));

  g_clear_pointer(&priv->dnd_target, gtk_target_entry_free);
  priv->dnd_target = gtk_target_entry_copy(target);
}

GtkTargetEntry *flow_grid_get_dnd_target ( GtkWidget *self )
{
  FlowGridPrivate *priv;

  g_return_val_if_fail(IS_FLOW_GRID(self), NULL);
  priv = flow_grid_get_instance_private(FLOW_GRID(self));

  return priv->dnd_target;
}

/* FlickOS: the same for the overflow list. */
static void flow_grid_remove_more_maybe (GtkWidget *widget, GtkWidget *self)
{
  FlowGridPrivate *priv;

  priv = flow_grid_get_instance_private(FLOW_GRID(self));
  if(!g_list_find(priv->children, widget))
    gtk_container_remove(GTK_CONTAINER(priv->more_grid), widget);
}

static void flow_grid_remove_widget_maybe (GtkWidget *widget, GtkWidget *self)
{
  FlowGridPrivate *priv;

  g_return_if_fail(IS_FLOW_GRID(self));
  priv = flow_grid_get_instance_private(FLOW_GRID(self));

  if(widget != priv->more_button && !g_list_find(priv->children, widget))
    gtk_container_remove (GTK_CONTAINER(priv->grid), widget);
}

/* FlickOS: upstream's taskbars, trays and pagers ran flow_grid_update()
 * every 100 ms for as long as they existed, and it did nothing unless the
 * grid was invalid: 10 wakeups a second per grid on an idle desktop. Now
 * flow_grid_invalidate() starts a one-shot 100 ms timeout on such a grid
 * instead, so changes are still batched and shown within 100 ms, and an
 * idle grid never wakes up. A grid invalidated during its own update gets
 * a new timeout, as the poll's next tick would have run it again. */
static gboolean flow_grid_update_cb ( GtkWidget *self )
{
  FlowGridPrivate *priv;

  priv = flow_grid_get_instance_private(FLOW_GRID(self));
  priv->update_h = 0;
  flow_grid_update(self);

  return G_SOURCE_REMOVE;
}

static void flow_grid_schedule_update ( GtkWidget *self )
{
  FlowGridPrivate *priv;

  priv = flow_grid_get_instance_private(FLOW_GRID(self));
  if(priv->auto_update && priv->invalid && !priv->update_h)
    priv->update_h = g_timeout_add(100, (GSourceFunc)flow_grid_update_cb,
        self);
}

void flow_grid_set_auto_update ( GtkWidget *self )
{
  FlowGridPrivate *priv;

  g_return_if_fail(IS_FLOW_GRID(self));
  priv = flow_grid_get_instance_private(FLOW_GRID(self));

  priv->auto_update = TRUE;
  /* A parent class's init may have invalidated the grid already. */
  flow_grid_schedule_update(self);
}

void flow_grid_invalidate ( GtkWidget *self )
{
  FlowGridPrivate *priv;
  GList *iter;

  g_return_if_fail(IS_FLOW_GRID(self));
  priv = flow_grid_get_instance_private(FLOW_GRID(self));

  for(iter=base_widget_get_mirror_children(self); iter; iter=g_list_next(iter))
    flow_grid_invalidate(iter->data);

  priv->invalid = TRUE;
  flow_grid_schedule_update(self);
}

void flow_grid_add_child ( GtkWidget *self, GtkWidget *child )
{
  FlowGridPrivate *priv;

  g_return_if_fail(IS_FLOW_GRID(self));
  priv = flow_grid_get_instance_private(FLOW_GRID(self));

  priv->children = g_list_append(priv->children, child);
  flow_item_set_parent(child, self);
  flow_grid_invalidate(self);
}

void flow_grid_delete_child ( GtkWidget *self, void *source )
{
  FlowGridPrivate *priv;
  GtkWidget *child;

  g_return_if_fail(IS_FLOW_GRID(self));
  priv = flow_grid_get_instance_private(FLOW_GRID(self));

  if( !(child = flow_grid_find_child(self, source)) )
    return;

  priv->children = g_list_remove(priv->children, child);
  g_object_unref(child);
  flow_grid_invalidate(self);
}

static void flow_grid_child_position ( GtkGrid *grid, GtkWidget *child,
    gint x, gint y )
{
  if(!gtk_widget_get_parent(child))
    gtk_grid_attach(GTK_GRID(grid), child, x, y, 1, 1);
  else
    gtk_container_child_set(GTK_CONTAINER(grid), child,
        "left-attach", x,
        "top-attach", y,
        "width", 1,
        "height", 1,
        NULL);
}

/* FlickOS: the overflow list is one row, wrapped at the screen's width, so
 * an item's own pop-up (an app's windows) opens above the list instead of
 * over its other items. */
static gint flow_grid_more_cols ( GtkWidget *self )
{
  GdkMonitor *mon;
  GdkRectangle space;
  gint w;

  w = flow_grid_more_width(self);
  if(w < 1 || !(mon = monitor_from_widget(self)))
    return 8;
  gdk_monitor_get_workarea(mon, &space);
  return MAX(1, (space.width - 32) / w);
}

/* FlickOS: put child at x, y of grid, taking it out of the other grid
 * (the bar's or the overflow list's) first. */
static void flow_grid_child_move ( GtkWidget *self, GtkWidget *grid,
    GtkWidget *child, gint x, gint y )
{
  FlowGridPrivate *priv;
  GtkWidget *parent;

  priv = flow_grid_get_instance_private(FLOW_GRID(self));
  parent = gtk_widget_get_parent(child);
  if(parent && parent != grid)
  {
    g_object_ref(child);
    gtk_container_remove(GTK_CONTAINER(parent), child);
    gtk_grid_attach(GTK_GRID(grid), child, x, y, 1, 1);
    g_object_unref(child);
  }
  else
    flow_grid_child_position(GTK_GRID(grid), child, x, y);

  if(parent != grid)
  {
    g_signal_handlers_disconnect_by_func(child,
        flow_grid_more_item_release, self);
    if(grid == priv->more_grid)
      g_signal_connect(child, "button-release-event",
          G_CALLBACK(flow_grid_more_item_release), self);
  }
}

/* FlickOS: the first priv->capacity items in the bar, the rest in the
 * overflow list, the more button after the bar's last item. */
static void flow_grid_overflow_place ( GtkWidget *self, gint count )
{
  FlowGridPrivate *priv;
  GtkWidget *parent;
  GList *iter;
  gint in_bar, i, j, cols;

  priv = flow_grid_get_instance_private(FLOW_GRID(self));
  in_bar = (priv->capacity < 0 || priv->capacity >= count)?
    count : priv->capacity;
  if(in_bar < count)
    flow_grid_more_init(self);
  cols = flow_grid_more_cols(self);

  i = 0;
  for(iter=priv->children; iter; iter=g_list_next(iter))
    if(flow_item_get_active(iter->data))
    {
      if(i < in_bar)
        flow_grid_child_move(self, priv->grid, iter->data, i, 0);
      else
      {
        j = i - in_bar;
        flow_grid_child_move(self, priv->more_grid, iter->data,
            j % cols, j / cols);
      }
      i++;
    }
    else if( (parent = gtk_widget_get_parent(iter->data)) &&
        (parent == priv->grid || parent == priv->more_grid) )
      gtk_container_remove(GTK_CONTAINER(parent), iter->data);

  if(!priv->more_button)
    return;
  if(in_bar < count)
    flow_grid_child_position(GTK_GRID(priv->grid), priv->more_button,
        in_bar, 0);
  else
  {
    flow_grid_more_close(self);
    if(flow_grid_more_shown(priv))
      gtk_container_remove(GTK_CONTAINER(priv->grid), priv->more_button);
  }
}

gboolean flow_grid_update ( GtkWidget *self )
{
  FlowGridPrivate *priv;
  GList *iter;
  gint count, i, span, dir, xadjust;
  gboolean axis_cols;

  g_return_val_if_fail(IS_FLOW_GRID(self), FALSE);
  priv = flow_grid_get_instance_private(FLOW_GRID(self));

  if(!priv->invalid)
    return TRUE;
  priv->invalid = FALSE;

  if(priv->primary_axis != FLOW_GRID_AXIS_DEFAULT)
    axis_cols = priv->primary_axis == FLOW_GRID_AXIS_COLS;
  else if(priv->cols > 0)
    axis_cols = TRUE;
  else if(priv->rows > 0)
    axis_cols = FALSE;
  else
  {
    gtk_widget_style_get(priv->grid, "direction", &dir, NULL);
    axis_cols = (dir == GTK_POS_TOP || dir == GTK_POS_BOTTOM);
  }

  gtk_container_foreach(GTK_CONTAINER(priv->grid),
      (GtkCallback)flow_grid_remove_widget_maybe, self);

  if(priv->sort)
  {
    priv->children = g_list_sort_with_data(priv->children,
        (GCompareDataFunc)flow_item_compare, self);
    if(priv->sort_reverse)
      priv->children = g_list_reverse(priv->children);
  }
  else if(priv->children &&
      FLOW_ITEM_GET_CLASS((GList *)(priv->children)->data)->alt_cmp)
    priv->children = g_list_sort_with_data(priv->children,
        FLOW_ITEM_GET_CLASS((GList *)(priv->children)->data)->alt_cmp, self);

  count = 0;
  for(iter=priv->children; iter; iter=g_list_next(iter))
  {
    flow_item_update(iter->data);
    if(flow_item_get_active(iter->data))
      count++;
  }

  gtk_container_foreach(GTK_CONTAINER(priv->grid),
      (GtkCallback)flow_grid_remove_widget_maybe, self);

  if(priv->sort)
  {
    priv->children = g_list_sort_with_data(priv->children,
        (GCompareDataFunc)flow_item_compare, self);
    if(priv->sort_reverse)
      priv->children = g_list_reverse(priv->children);
  }

  count = 0;
  for(iter=priv->children; iter; iter=g_list_next(iter))
  {
    flow_item_update(iter->data);
    if(flow_item_get_active(iter->data))
      count++;
  }

  if(priv->more_grid)
    gtk_container_foreach(GTK_CONTAINER(priv->more_grid),
        (GtkCallback)flow_grid_remove_more_maybe, self);

  if(flow_grid_overflow_on(priv))
  {
    flow_grid_overflow_place(self, count);
    css_widget_cascade(self, NULL);
    return TRUE;
  }
  /* FlickOS: overflow turned off, or more than one row: every item back in
   * the bar. */
  if(priv->more_button)
  {
    priv->capacity = -1;
    flow_grid_overflow_place(self, count);
  }

  if(axis_cols)
    span = priv->rows>0? priv->rows :
      (count/MAX(priv->cols, 1)) + !!(count%MAX(priv->cols, 1));
  else
    span = priv->cols>0? priv->cols :
      (count/MAX(priv->rows, 1)) + !!(count%MAX(priv->rows, 1));

  if(!span)
    return TRUE;

  i = 0;
  xadjust = count%span && axis_cols^(priv->rows>0);
  for(iter=priv->children; iter; iter=g_list_next(iter))
    if(flow_item_get_active(iter->data))
    {
      flow_grid_child_position(GTK_GRID(priv->grid), iter->data,
          axis_cols? i/span : i%span, axis_cols? i%span : i/span);
      i += 1 + (xadjust && i%span==span-2 && i/span>=count%span);
    }
    else if(gtk_widget_get_parent(iter->data) == priv->grid)
      gtk_container_remove(GTK_CONTAINER(priv->grid), iter->data);

  if(FLOW_GRID_GET_CLASS(self)->fill)
    for(;i<span; i++)
      gtk_grid_attach(GTK_GRID(priv->grid), gtk_label_new(""),
          axis_cols? 0 : i, axis_cols? i : 0, 1, 1);
  css_widget_cascade(self, NULL);

  return TRUE;
}

guint flow_grid_n_children ( GtkWidget *self, gboolean active )
{
  FlowGridPrivate *priv;
  GList *iter;
  guint n = 0;

  g_return_val_if_fail(IS_FLOW_GRID(self),0);
  priv = flow_grid_get_instance_private(FLOW_GRID(self));

  for(iter=priv->children; iter; iter=g_list_next(iter))
    if(!active || flow_item_get_active(iter->data))
      n++;

  return n;
}

gpointer flow_grid_get_sole_source ( GtkWidget *self )
{
  FlowGridPrivate *priv;
  GList *iter;
  gpointer source = NULL;

  g_return_val_if_fail(IS_FLOW_GRID(self), NULL);
  priv = flow_grid_get_instance_private(FLOW_GRID(self));

  for(iter=priv->children; iter; iter=g_list_next(iter))
    if(flow_item_get_active(iter->data))
    {
      if(source)
        return NULL;
      else
        source = flow_item_get_source(iter->data);
    }

  return source;
}

GtkWidget *flow_grid_find_child ( GtkWidget *self, gconstpointer source )
{
  FlowGridPrivate *priv;
  GList *iter;

  g_return_val_if_fail(IS_FLOW_GRID(self), NULL);
  priv = flow_grid_get_instance_private(FLOW_GRID(self));

  iter = g_list_find_custom(priv->children, source,
      (GCompareFunc)flow_item_check_source);
  return iter? iter->data : NULL;
}

void flow_grid_children_order ( GtkWidget *self, GtkWidget *ref,
    GtkWidget *child, gboolean after )
{
  FlowGridPrivate *priv;
  GList *dlist;

  g_return_if_fail(IS_FLOW_GRID(self));
  priv = flow_grid_get_instance_private(FLOW_GRID(self));

  dlist = g_list_find(priv->children, ref);
  if(!dlist || !g_list_find(priv->children, child))
    return;

  priv->children = g_list_remove(priv->children, child);
  priv->children = g_list_insert_before(priv->children,
      after ? g_list_next(dlist) : dlist, child);

  flow_item_invalidate(child);
  flow_item_invalidate(ref);
}

GList *flow_grid_children_get ( GtkWidget *self )
{
  FlowGridPrivate *priv;

  g_return_val_if_fail(IS_FLOW_GRID(self), NULL);
  priv = flow_grid_get_instance_private(FLOW_GRID(self));

  return priv->children;
}
